import json
import os
from utils import *
import pandas as pd

region_name_mapping = json.load(open("region_name_mapping.json"))
for region_name_key in region_name_mapping.keys():
    demand_file = f'inner_trips/{region_name_key}_inner.csv'
    region_name = region_name_mapping[region_name_key]

    min_start_time = 9 * 3600
    max_start_time = 10 * 3600

    PADDING = 0.001

    try_up_to_num_paths = 5

    source_osm = 'ile-de-france.osm.pbf'
    data_url = "https://download.geofabrik.de/europe/france/ile-de-france-latest.osm.pbf"
    download_osm_file(data_url, source_osm)

    demand_df = pd.read_csv(demand_file)
    demand_df = demand_df[["departure_time","ox","oy","dx","dy"]]
    demand_df["dest_edge"] = None
    demand_df["origin_edge"] = None
    demand_df.head()

    demand_df = demand_df[demand_df["departure_time"].between(min_start_time, max_start_time)]
    demand_df["departure_time"] = demand_df["departure_time"] - min_start_time
    demand_df["departure_time"] = demand_df["departure_time"].astype(int)
    demand_df = demand_df.reset_index(drop=True)

    print(len(demand_df))
    print(min(demand_df["departure_time"]))
    print(max(demand_df["departure_time"]))

    min_y = min(demand_df['oy'].min(), demand_df['dy'].min())
    max_y = max(demand_df['oy'].max(), demand_df['dy'].max())
    min_x = min(demand_df['ox'].min(), demand_df['dx'].min())
    max_x = max(demand_df['ox'].max(), demand_df['dx'].max())
    print("min_y: ", min_y)
    print("max_y: ", max_y)
    print("min_x: ", min_x)
    print("max_x: ", max_x)

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
    filter_passenger_edges(edg_file, edg_file)