import argparse
import os
import janux 
import networkx as nx
import pandas as pd
import json

from utils import *

import warnings
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--region', type=str, required=True, help='Region name key (e.g., region_1)')
    parser.add_argument('--min-start', type=int, default=9*3600, help='Minimum start time in seconds (default: 9*3600)')
    parser.add_argument('--max-start', type=int, default=9.5*3600, help='Maximum start time in seconds (default: 9.5*3600)')
    parser.add_argument('--num-paths', type=int, default=4, help='Number of paths to try for routing (default: 4)')
    args = parser.parse_args()
    region_name = args.region
    min_start_time = args.min_start
    max_start_time = args.max_start
    try_up_to_num_paths = args.num_paths
    
    demand_file = f'inner_trips/{region_name}_inner.csv'
    region_name_mapping = json.load(open("inner_trips/region_name_mapping.json"))
    print(f"------ RUNNING FOR {region_name} ({region_name_mapping[region_name]}) ------\n")
    
    region_name = region_name_mapping[region_name]
    PADDING = 0.001
    TIMEOUT = 10
    
    """
    Download the Ile-de-france OSM file if it doesn't exist
    """
    source_osm = 'ile-de-france.osm.pbf'
    data_url = "https://download.geofabrik.de/europe/france/ile-de-france-latest.osm.pbf"
    download_osm_file(data_url, source_osm)

    """
    Read demand data
    """
    demand_df = pd.read_csv(demand_file)
    demand_df = demand_df[["departure_time", "ox", "oy", "dx", "dy"]]
    demand_df["dest_edge"] = None
    demand_df["origin_edge"] = None

    """
    Retrieve coordinate boundaries of the demand
    """
    min_y = min(demand_df['oy'].min(), demand_df['dy'].min())
    max_y = max(demand_df['oy'].max(), demand_df['dy'].max())
    min_x = min(demand_df['ox'].min(), demand_df['dx'].min())
    max_x = max(demand_df['ox'].max(), demand_df['dx'].max())
    
    """
    Filter out departure times according to the given time window
    """
    demand_df = demand_df[demand_df["departure_time"].between(min_start_time, max_start_time)]
    demand_df["departure_time"] = demand_df["departure_time"] - min_start_time
    demand_df["departure_time"] = demand_df["departure_time"].astype(int)
    demand_df = demand_df.reset_index(drop=True)
    print(f"Remaining trips after departure time filtering: {len(demand_df)}")

    """
    Creating files needed for SUMO simulation
    """
    # File names
    osm_file = region_name + '/' + '.'.join([region_name, 'osm'])
    net_file = region_name + '/' + '.'.join([region_name, 'net', 'xml'])
    rou_file = region_name + '/' + '.'.join([region_name, 'rou', 'xml'])
    con_file = region_name + '/' + ".".join([region_name, 'con' ,'xml'])
    edg_file = region_name + '/' + ".".join([region_name, 'edg' ,'xml'])
    nod_file = region_name + '/' + ".".join([region_name, 'nod' ,'xml'])
    tll_file = region_name + '/' + ".".join([region_name, 'tll' ,'xml'])
    typ_file = region_name + '/' + ".".join([region_name, 'typ' ,'xml'])

    if not os.path.exists(region_name):
        os.makedirs(region_name)
        
    extract_bbox(source_osm, osm_file, min_x-PADDING, min_y-PADDING, max_x+PADDING, max_y+PADDING)
    convert_osm_to_net(osm_file, net_file)
    convert_net_to_rou(net_file, rou_file)
    create_sumo_miscellaneous(region_name, net_file)
    filter_passenger_edges(edg_file, edg_file) # Filter out non-passenger edges

    """
    Map trips to edges in the network
    """
    
    node_xy = extract_nodes_from_osm(osm_file)
    nodes, edges = janux.visualizers.visualization_utils.parse_network_files(nod_file, edg_file)
    G = janux.visualizers.visualization_utils.create_graph(nodes, edges) # Create a graph from the nodes and edges

    # Create dictionaries for edges (used for final formatting)
    edges_od_to_id = {}
    for o, d, edge_id in edges:
        edges_od_to_id[(o, d)] = edge_id
    edges_id_to_od = {}
    for o, d, edge_id in edges:
        edges_id_to_od[edge_id] = (o, d)

    # Create a dictionary for edge coordinates, approximated as the midpoint of connected nodes
    edges_xy = {}
    for o, d in G.edges():
        try:
            o_xy = node_xy[o]
            d_xy = node_xy[d]
            mid_xy = ((o_xy[0] + d_xy[0]) / 2, (o_xy[1] + d_xy[1]) / 2)
            edges_xy[(o, d)] = mid_xy
        except:
            continue

    # Find non-dead-end origin candidates and accessible destination candidates
    network = janux.build_digraph(con_file, edg_file, rou_file)
    origin_candidates, destination_candidates = [], []
    for idx, node in enumerate(network.nodes()):
        print(f"\rProcessing... {idx+1}/{len(network.nodes())}", end="")
        # paths from nodes
        paths_from = nx.descendants(network, node)
        # paths to nodes
        paths_to = nx.ancestors(network, node)
        if len(paths_from) > 0:
            origin_candidates.append(node)
        if len(paths_to) > 0:
            destination_candidates.append(node)

    # Mapping each trip to the closest edges
    for idx, row in demand_df.iterrows():
        print(f"\r{idx+1}/{len(demand_df)}", end="")
        o_xy = (row['ox'], row['oy'])
        d_xy = (row['dx'], row['dy'])
        
        # Find the closest edge to the origin from edges_xy
        origin_edge = find_nearest_edge(row['ox'], row['oy'], origin_candidates, edges_xy, edges_id_to_od)
        dest_edge = find_nearest_edge(row['dx'], row['dy'], destination_candidates, edges_xy, edges_id_to_od)
        
        if origin_edge is None or dest_edge is None:
            raise ValueError(f"Could not find nearest edge for origin ({row['ox']}, {row['oy']}) or destination ({row['dx']}, {row['dy']})")
        demand_df.at[idx, 'origin_edge'] = origin_edge
        demand_df.at[idx, 'dest_edge'] = dest_edge

    """
    Filter out undesirable trips
    """
    
    network = janux.build_digraph(con_file, edg_file, rou_file)
    demand_df.rename(columns={"departure_time": "start_time"}, inplace=True)
    demand_df.rename(columns={"origin_edge": "origin"}, inplace=True)
    demand_df.rename(columns={"dest_edge": "destination"}, inplace=True)

    # Remove trips with inaccessible origins or destinations
    print("Removing trips with inaccessible origins or destinations...")

    origins, destinations = demand_df["origin"].unique(), demand_df["destination"].unique()
    bad_origins, bad_destinations = [], []
    reversed_network = network.reverse()
    
    # origins with no outlinks
    for idx, origin in enumerate(origins):
        print(f"\r{idx+1}/{len(origins)}: Deleted: {len(bad_origins)}", end="")
        try:
            paths_from_origin = nx.multi_source_dijkstra_path(network, [origin])
            del paths_from_origin[origin]
            if len(paths_from_origin) == 0:
                bad_origins.append(origin)
        except:
            bad_origins.append(origin)
    
    # inaccessible destinations       
    for idx, destination in enumerate(destinations):
        print(f"\r{idx+1}/{len(destinations)}: Deleted: {len(bad_destinations)}", end="")
        try:
            paths_from_destination = nx.multi_source_dijkstra_path(reversed_network, [destination])
            del paths_from_destination[destination]
            if len(paths_from_destination) == 0:
                bad_destinations.append(destination)
        except:
            bad_destinations.append(destination)
            
    for idx, row in demand_df.iterrows():
        if row["origin"] in bad_origins or row["destination"] in bad_destinations:
            demand_df.drop(idx, inplace=True)
            
    print(f"\nDeleted {len(bad_origins)} origins and {len(bad_destinations)} destinations")

    # Remove trips with identical origin and destination
    print("Removing trips with identical origin and destination...")
    counter = 0
    for idx, row in demand_df.iterrows():
        if row["origin"] == row["destination"]:
            demand_df.drop(idx, inplace=True)
            counter += 1
    print(f"Deleted {counter} trips with identical origin and destination")

    # Reset indices and row IDs
    demand_df.reset_index(drop=True, inplace=True)
    demand_df["id"] = [i for i in range(len(demand_df))]

    """
    - We cannot generate multiple routes for some of the trips.
    - Therefore, they are not suitable for route choice.
    - We will remove these trips from the demand.
    - We will use JanuX for this purpose, see: ```https://github.com/COeXISTENCE-PROJECT/JanuX```.
    - JanuX assumes that it is always possible to find desired number of routes between any two nodes.
    - However, this is not the case in our network.
    
    We will use the following approach:
    1. For increasing number of paths, we will try to find the routes.
    2. For each trip, we will try to find the routes.
    3. If we cannot find the routes before a predefined timeout, we will remove the trip from the demand.
    4. We will repeat this process for all trips.
    """

    print("\nPruning demand with JanuX...\n")

    bad_demand = set()
    counter = 0
    
    for num_paths in range(try_up_to_num_paths):
        results = route_gen_process(network, demand_df, num_paths+1, TIMEOUT)
        for d in results:
            bad_demand.add(d)
        for idx, row in demand_df.iterrows():
            if (row["origin"], row["destination"]) in results:
                demand_df.drop(idx, inplace=True)       
                counter += 1
    print(f"Deleted {counter} trips with bad demand")

    # Reset indices
    demand_df.reset_index(drop=True, inplace=True)
    demand_df["id"] = [i for i in range(len(demand_df))]

    """
    Reformat and save data for URB.
    Following lines can be modified to save the data in a different format.
    """

    # Convert origin and destination names to indices
    origin_indices = {origin_name : idx for idx, origin_name in enumerate(demand_df["origin"].unique())}
    destination_indices = {destination_name : idx for idx, destination_name in enumerate(demand_df["destination"].unique())}

    origin_names = {value: key for key, value in origin_indices.items()}
    destination_names = {value: key for key, value in destination_indices.items()}

    for idx, row in demand_df.iterrows():
        demand_df.at[idx, "origin"] = origin_indices[row["origin"]]
        demand_df.at[idx, "destination"] = destination_indices[row["destination"]]

    # Rename columns
    demand_df = demand_df[["id", "origin", "destination", "start_time"]]
    # Add a column for the agent kind (Human), they can mutate to AVs during the experiment.
    demand_df["kind"] = "Human"
    # Save the demand data to a CSV file
    demand_df.to_csv(f"{region_name}/agents.csv", index=False)
    print("Agents are saved.")

    # We saved trip origin and destinations by their indices.
    # Now we need to save their edge IDs, ordered by their indices.
    # This will be resolved by `URB` scripts appropriately.
    keys = [k for k in origin_names.keys()]
    origins = [origin_names[k] for k in keys]
    keys = [k for k in destination_names.keys()]
    destinations = [destination_names[k] for k in keys]
    
    filename = f"{region_name}/od_{region_name}.txt"
    with open(filename, 'w') as f:
        f.write("{\n")
        f.write(f"\"origins\" : {origins},\n")
        f.write(f"\"destinations\" : {destinations},\n")
        f.write("}")
    print(f"OD pairs are saved to {filename}")
    
    print("Done.")
    print("--------------------------------------------------")