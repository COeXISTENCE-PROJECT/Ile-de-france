# %%
import argparse
import os
import janux 
import networkx as nx
import pandas as pd
import json

from concurrent.futures import ProcessPoolExecutor, as_completed

from utils import *

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--region', type=str, required=True, help='Region name key (e.g., region_1)')
    args = parser.parse_args()
    region_name = args.region
    
    demand_file = f'inner_trips/{region_name}_inner.csv'

    region_name_mapping = json.load(open("region_name_mapping.json"))
    print(f"------ RUNNING FOR {region_name} ({region_name_mapping[region_name]}) ------\n")
    region_name = region_name_mapping[region_name]

    min_start_time = 9 * 3600
    max_start_time = 10 * 3600
    
    pre_filtering_size = 2000
    final_filtering_size = 1000

    PADDING = 0.001
    
    try_up_to_num_paths = 4

    # %%
    source_osm = 'ile-de-france.osm.pbf'
    data_url = "https://download.geofabrik.de/europe/france/ile-de-france-latest.osm.pbf"
    download_osm_file(data_url, source_osm)

    # %% [markdown]
    # # Read demand

    # %%
    demand_df = pd.read_csv(demand_file)
    demand_df = demand_df[["departure_time","ox","oy","dx","dy"]]
    demand_df["dest_edge"] = None
    demand_df["origin_edge"] = None
    demand_df.head()

    # %% [markdown]
    # ### Filter out departure times

    # %%
    demand_df = demand_df[demand_df["departure_time"].between(min_start_time, max_start_time)]
    demand_df["departure_time"] = demand_df["departure_time"] - min_start_time
    demand_df["departure_time"] = demand_df["departure_time"].astype(int)
    demand_df = demand_df.reset_index(drop=True)

    print(len(demand_df))
    print(min(demand_df["departure_time"]))
    print(max(demand_df["departure_time"]))

    # %% [markdown]
    # # Boundaries

    # %%
    min_y = min(demand_df['oy'].min(), demand_df['dy'].min())
    max_y = max(demand_df['oy'].max(), demand_df['dy'].max())
    min_x = min(demand_df['ox'].min(), demand_df['dx'].min())
    max_x = max(demand_df['ox'].max(), demand_df['dx'].max())
    print("min_y: ", min_y)
    print("max_y: ", max_y)
    print("min_x: ", min_x)
    print("max_x: ", max_x)

    # %% [markdown]
    # # Creating files

    # %%
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


    # %%
    extract_bbox(source_osm, osm_file, min_x-PADDING, min_y-PADDING, max_x+PADDING, max_y+PADDING)
    convert_osm_to_net(osm_file, net_file)
    convert_net_to_rou(net_file, rou_file)
    create_sumo_miscellaneous(region_name, net_file)

    # %% [markdown]
    # # Map demand to edges

    # %%
    node_xy = extract_nodes_from_osm(osm_file)

    # %%
    nodes, edges = janux.visualizers.visualization_utils.parse_network_files(nod_file, edg_file)
    G = janux.visualizers.visualization_utils.create_graph(nodes, edges)

    # %%
    edges_od_to_id = {}
    for o, d, edge_id in edges:
        edges_od_to_id[(o, d)] = edge_id
    edges_id_to_od = {}
    for o, d, edge_id in edges:
        edges_id_to_od[edge_id] = (o, d)

    # %%
    edges_xy = {}
    for o, d in G.edges():
        try:
            o_xy = node_xy[o]
            d_xy = node_xy[d]
            mid_xy = ((o_xy[0] + d_xy[0]) / 2, (o_xy[1] + d_xy[1]) / 2)
            edges_xy[(o, d)] = mid_xy
        except:
            continue

    # %%
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
    print("\norigin_candidates: ", len(origin_candidates))
    print("destination_candidates: ", len(destination_candidates))

    # %%
    for idx, row in demand_df.iterrows():
        print(f"\r{idx+1}/{len(demand_df)}", end="")
        o_xy = (row['ox'], row['oy'])
        d_xy = (row['dx'], row['dy'])
        
        # Find the closest edge to the origin from edges_xy
        origin_edge = find_nearest_edge(row['ox'], row['oy'], origin_candidates, edges_xy, edges_id_to_od)
        #origin_edge = edges_od_to_id.get(origin_edge, None)
        dest_edge = find_nearest_edge(row['dx'], row['dy'], destination_candidates, edges_xy, edges_id_to_od)
        #dest_edge = edges_od_to_id.get(dest_edge, None)
        
        if origin_edge is None or dest_edge is None:
            raise ValueError(f"Could not find nearest edge for origin ({row['ox']}, {row['oy']}) or destination ({row['dx']}, {row['dy']})")
        demand_df.at[idx, 'origin_edge'] = origin_edge
        demand_df.at[idx, 'dest_edge'] = dest_edge


    # %%
    sample_demand = demand_df.sample(5)

    for idx, sample in sample_demand.iterrows():
        print(f"Demand origin x: {sample['ox']}, y: {sample['oy']} is mapped to edge {sample['origin_edge']}")
        print(f"Demand destination x: {sample['dx']}, y: {sample['dy']} is mapped to edge {sample['dest_edge']}")

    # %%
    sample_demand

    # %% [markdown]
    # # Filter out undesirable ones

    # %%
    network = janux.build_digraph(con_file, edg_file, rou_file)

    demand_df.rename(columns={"departure_time": "start_time"}, inplace=True)
    demand_df.rename(columns={"origin_edge": "origin"}, inplace=True)
    demand_df.rename(columns={"dest_edge": "destination"}, inplace=True)

    # %%
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
    
    print("\n")
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

    # %%
    print("Removing trips with identical origin and destination...")
    counter = 0
    for idx, row in demand_df.iterrows():
        if row["origin"] == row["destination"]:
            demand_df.drop(idx, inplace=True)
            counter += 1
    print(f"Deleted {counter} trips with identical origin and destination")

    # %%
    demand_df.reset_index(drop=True, inplace=True)
    demand_df["id"] = [i for i in range(len(demand_df))]

    # %% [markdown]
    # # Prune non-route-choice-able demand using JanuX

    # %%
    print("\nPruning demand with JanuX...")
    
    if len(demand_df) > pre_filtering_size:
        demand_df = demand_df.sample(pre_filtering_size, random_state=42)
        demand_df.reset_index(drop=True, inplace=True)
        demand_df["id"] = [i for i in range(len(demand_df))]
        print(f"Sampled {pre_filtering_size} demands for pruning")

    # %%
    bad_demand = set()
    counter = 0
    
    for num_paths in range(try_up_to_num_paths):
        print(f"\nTrying with {num_paths+1} paths...")
        results = route_gen_process(network, demand_df, num_paths+1, 10)
        for d in results:
            bad_demand.add(d)
        for idx, row in demand_df.iterrows():
            if (row["origin"], row["destination"]) in results:
                demand_df.drop(idx, inplace=True)       
                counter += 1
    
        
    bad_demand = list(bad_demand)
    print(f"\nOverall bad demands: {bad_demand}")
    print(f"Deleted {counter} trips with bad demand")

    # %%
    # Reset indices
    demand_df.reset_index(drop=True, inplace=True)
    demand_df["id"] = [i for i in range(len(demand_df))]
    
    if len(demand_df) > final_filtering_size:
        demand_df = demand_df.sample(final_filtering_size, random_state=42)
        demand_df.reset_index(drop=True, inplace=True)
        demand_df["id"] = [i for i in range(len(demand_df))]
        print(f"\nSampled {final_filtering_size} demands.")

    # %% [markdown]
    # # Turn it into our format

    # %%
    origin_indices = {origin_name : idx for idx, origin_name in enumerate(demand_df["origin"].unique())}
    destination_indices = {destination_name : idx for idx, destination_name in enumerate(demand_df["destination"].unique())}

    origin_names = {value: key for key, value in origin_indices.items()}
    destination_names = {value: key for key, value in destination_indices.items()}

    for idx, row in demand_df.iterrows():
        demand_df.at[idx, "origin"] = origin_indices[row["origin"]]
        demand_df.at[idx, "destination"] = destination_indices[row["destination"]]

    # %%
    demand_df

    # %%
    demand_df.to_csv(f"{region_name}/agents_{region_name}.csv", index=False)
    print("Agents are saved.")

    # %%
    print("Origins:")
    keys = [k for k in origin_names.keys()]
    print(keys == sorted(keys))
    origins = [origin_names[k] for k in keys]
    print(origins)

    # %%
    print("Destinations:")
    keys = [k for k in destination_names.keys()]
    print(keys == sorted(keys))
    destinations = [destination_names[k] for k in keys]
    print(destinations)

    # %%
    filename = f"{region_name}/od_{region_name}.txt"
    with open(filename, 'w') as f:
        f.write(f"ORIGINS:\n")
        f.write(f"{origins}\n")
        f.write(f"DESTINATIONS:\n")
        f.write(f"{destinations}\n")
    print(f"OD pairs are saved to {filename}")


