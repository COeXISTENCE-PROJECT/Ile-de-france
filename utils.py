import os
import janux 
import signal
import subprocess
import requests   
import xml.etree.ElementTree as ET

from geopy.geocoders import Nominatim

#########

def download_osm_file(url, output_file):
    if os.path.exists(output_file):
        print(f"File '{output_file}' already exists. Skipping download.")
        return
    else:
        print(f"Downloading {url} ...")

    response = requests.get(url, stream=True)
    if response.status_code == 200:
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        with open(output_file, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
                downloaded_size += len(chunk)
                print(f"\rDownloaded {downloaded_size / total_size * 100:.2f}%", end="")
        print(f"\nDownload complete: {output_file}")
    else:
        print(f"Failed to download file. Status code: {response.status_code}")
        
#########      

class extract_bbox:
    
    def __init__(self, input_file, output_file, min_lon, min_lat, max_lon, max_lat):
        """
        city: The name of the city you would like to export
        input_file: The input file in osm.pbf format
        output_file: The name of the output file in filename.osm format
        """
        self.input_file = input_file
        self.output_file = output_file

        self.existence = self.existence_check()

        if self.existence:
            self.min_lon = min_lon
            self.min_lat = min_lat
            self.max_lon = max_lon
            self.max_lat = max_lat

            self.extract_osm()


    def extract_osm(self):
        cmd = [
            "osmium",
            "extract",
            "--bbox",
            f"{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}",
            "-o",
            self.output_file,
            self.input_file
        ]
        subprocess.run(cmd)

    def existence_check(self):
        if os.path.exists(self.output_file):
            print(f"File '{self.output_file}' already exists.")
            return 0
        else:
            return 1
        
#########

def extract_nodes_from_osm(osm_file):
    tree = ET.parse(osm_file)
    root = tree.getroot()

    nodes = {}

    for node in root.findall('node'):
        node_id = node.attrib['id']
        lat = node.attrib['lat']
        lon = node.attrib['lon']
        nodes[node_id] = (float(lon), float(lat))

    return nodes

#########

def convert_osm_to_net(input_file, output_file):
    if os.path.exists(output_file):
        print(f"File '{output_file}' already exists.")
        return
    else:
        print(f"Creating '{output_file}' ...")

    net_to_osm_convert_cmd = [
        "netconvert",
        "--osm-files",
        input_file,
        "--output-file",
        output_file,
        "--geometry.remove",
        "--junctions.join=false",
        "--roundabouts.guess",
        "--tls.discard-simple",
        "--remove-edges.isolated",
        "--verbose",
        "--ramps.guess",
        "--tls.guess-signals",
        "--tls.join",
        "--tls.ignore-internal-junction-jam"
    ]

    subprocess.run(net_to_osm_convert_cmd, capture_output=True, text=True)
    
#########    

import xml.etree.ElementTree as ET

def filter_passenger_lanes_and_connections(input_file, output_file):
    tree = ET.parse(input_file)
    root = tree.getroot()

    valid_edges = set()
    referenced_nodes = set()

    # === First Pass: Filter lanes and collect valid edges and referenced nodes ===
    for edge in list(root.findall('edge')):
        lanes = list(edge.findall('lane'))
        for lane in lanes:
            allow = lane.get('allow')
            disallow = lane.get('disallow')

            if allow:
                allowed = set(allow.split())
                if 'passenger' not in allowed:
                    edge.remove(lane)
            elif disallow:
                disallowed = set(disallow.split())
                if 'passenger' in disallowed:
                    edge.remove(lane)

        remaining_lanes = edge.findall('lane')
        if remaining_lanes:
            edge_id = edge.get('id')
            valid_edges.add(edge_id)
            referenced_nodes.add(edge.get('from'))
            referenced_nodes.add(edge.get('to'))
        else:
            root.remove(edge)

    # === Second Pass: Remove invalid connections ===
    for conn in list(root.findall('connection')):
        from_edge = conn.get('from')
        to_edge = conn.get('to')
        from_lane = conn.get('fromLane')
        to_lane = conn.get('toLane')

        from_lane_id = f"{from_edge}_{from_lane}" if from_lane else None
        to_lane_id = f"{to_edge}_{to_lane}" if to_lane else None

        if (from_edge not in valid_edges or to_edge not in valid_edges):
            root.remove(conn)
            continue

    # === Third Pass: Rebuild list of all valid lanes ===
    valid_lanes = {lane.get("id") for lane in root.findall(".//lane")}

    # === Fourth Pass: Clean and validate junctions ===
    for junction in list(root.findall('junction')):
        j_id = junction.get('id')

        # Filter incLanes
        inc_lanes = junction.get('incLanes')
        filtered_inc = []
        if inc_lanes:
            filtered_inc = [lane for lane in inc_lanes.split() if lane in valid_lanes]
            if filtered_inc:
                junction.set('incLanes', ' '.join(filtered_inc))
            else:
                junction.attrib.pop('incLanes', None)

        # Filter intLanes
        int_lanes = junction.get('intLanes')
        filtered_int = []
        if int_lanes:
            filtered_int = [lane for lane in int_lanes.split() if lane in valid_lanes]
            if filtered_int:
                junction.set('intLanes', ' '.join(filtered_int))
            else:
                junction.attrib.pop('intLanes', None)

        is_used_by_edges = j_id in referenced_nodes
        has_valid_incoming = bool(filtered_inc)

        if not is_used_by_edges and not has_valid_incoming:
            root.remove(junction)

    # === Fifth Pass: Remove traffic lights with missing junctions ===
    existing_junctions = {j.get('id') for j in root.findall('junction')}
    for tl in list(root.findall('tlLogic')):
        if tl.get('id') not in existing_junctions:
            root.remove(tl)

    tree.write(output_file)

########

def filter_passenger_edges(input_file, output_file, allowed_types=None):
    import xml.etree.ElementTree as ET

    tree = ET.parse(input_file)
    root = tree.getroot()

    if allowed_types is None:
        allowed_types = {
            "highway.motorway",
            "highway.trunk",
            "highway.primary",
            "highway.secondary",
            "highway.tertiary",
            "highway.residential",
            "highway.unclassified",
            "highway.living_street",
        }

    for edge in list(root.findall("edge")):
        edge_type = edge.get("type")
        if edge_type not in allowed_types:
            root.remove(edge)

    tree.write(output_file)
    
#########
    
def convert_net_to_rou(input_file, output_file):
    if os.path.exists(output_file):
        print(f"File '{output_file}' already exists.")
        return
    else:
        print(f"Creating '{output_file}' ...")

    net_to_rou_convert_cmd = [
        "netconvert",
        "--s",
        input_file,
        "-o",
        output_file
    ]

    subprocess.run(net_to_rou_convert_cmd)
 
#########   
    
def create_sumo_miscellaneous(net_name, net_file):
    con_file = net_name + '/' + ".".join([net_name, 'con' ,'xml'])
    edg_file = net_name + '/' + ".".join([net_name, 'edg' ,'xml'])
    nod_file = net_name + '/' + ".".join([net_name, 'nod' ,'xml'])
    tll_file = net_name + '/' + ".".join([net_name, 'tll' ,'xml'])
    typ_file = net_name + '/' + ".".join([net_name, 'typ' ,'xml'])

    existence_of_all_files = (os.path.exists(con_file) and
                              os.path.exists(edg_file) and
                              os.path.exists(nod_file) and
                              os.path.exists(tll_file) and
                              os.path.exists(typ_file))
    if existence_of_all_files:
        print(f"Necessary files already exist.")
        return
    else:
        print(f"Creating {net_name} '{con_file}' ...")
        print(f"Creating {net_name} '{edg_file}' ...")
        print(f"Creating {net_name} '{nod_file}' ...")
        print(f"Creating {net_name} '{tll_file}' ...")
        print(f"Creating {net_name} '{typ_file}' ...")

    miscellaneous_create = [
        "netconvert",
        "--sumo-net-file",
        net_file,
        "--plain-output-prefix",
        net_name + '/' + net_name
    ]

    subprocess.run(miscellaneous_create)

#########    
    
def find_nearest_edge(x, y, candidates, edges_xy, edges_id_to_od):
    closest_edge = None
    min_distance = float('inf')
    for edge in candidates:
        try:
            od = edges_id_to_od[edge]
            mid_xy = edges_xy[od]
            distance = ((x - mid_xy[0]) ** 2 + (y - mid_xy[1]) ** 2) ** 0.5
            if distance < min_distance:
                min_distance = distance
                closest_edge = edge
        except:
            continue
    return closest_edge

#########

class TimeoutException(Exception):
    pass

def handler(signum, frame):
    raise TimeoutException("Function timed out")

def run_with_timeout(func, timeout, *args, **kwargs):
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)  # Set the timeout alarm

    try:
        result = func(*args, **kwargs)
        signal.alarm(0)
        return result
    except TimeoutException as e:
        return None
    
######### 
    
def route_gen_process(network, df, num_paths, timeout=10):
    #print(f"\nGenerating paths for {num_paths} paths...")
    path_gen_kwargs = {
                "number_of_paths": num_paths,
                "random_seed": 42,
                "num_samples": 20,
                "beta": -5,
                "weight": "time",
                "verbose": False
            }
    
    unique_demands = df[["origin", "destination"]].apply(tuple, axis=1).tolist()
    unique_demands = list(set(unique_demands))
    bad_demand = set()
    validated_demand = set()
    for idx, demand in enumerate(unique_demands):
        print(f"{idx} of {len(unique_demands)}")
        o, d = demand
        if ((o, d) in bad_demand) or ((o, d) in validated_demand):
            continue
        try:
            routes = run_with_timeout(janux.extended_generator, timeout, network, [o], [d], as_df=True, calc_free_flow=True, **path_gen_kwargs)
        except:
            routes = None
        if routes is None:
            #print(f"\n{row['id']} failed for {row['origin']} to {row['destination']}")
            bad_demand.add((o, d))
        else:
            validated_demand.add((o, d))
      
    bad_demand  = list(bad_demand)
    print(f"\nBad demands for num_paths {num_paths}: {bad_demand}")
    
    return bad_demand