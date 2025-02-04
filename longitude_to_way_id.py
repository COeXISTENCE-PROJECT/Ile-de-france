import requests

# Coordinates for the location you want to query
latitude = 48.539813
longitude = 3.354430
radius = 50  # Search radius in meters

# Overpass API query for ways and their nodes within the radius
overpass_url = "http://overpass-api.de/api/interpreter"
overpass_query = f"""
<osm-script output="json">
  <query type="way">
    <around lat="{latitude}" lon="{longitude}" radius="{radius}"/>
  </query>
  <print/>
  <recurse type="way-node"/>
  <query type="node">
    <around lat="{latitude}" lon="{longitude}" radius="{radius}"/>
  </query>
  <print/>
</osm-script>
"""

response = requests.get(overpass_url, params={'data': overpass_query})

# Check if the response was successful
if response.status_code == 200:
    data = response.json()
    
    # Separate ways and nodes
    ways = [way for way in data['elements'] if way['type'] == 'way' and 'building' not in way.get('tags', {})]
    nodes = {node['id']: node for node in data['elements'] if node['type'] == 'node'}
    
    # Cross-reference nodes with non-building ways
    nodes_in_non_building_ways = set()
    for way in ways:
        if 'building' not in way.get('tags', {}):  # Exclude ways tagged as 'building'
            for node_id in way.get('nodes', []):  # Collect node IDs from the way
                if node_id in nodes:  # Ensure the node exists in the data
                    nodes_in_non_building_ways.add(node_id)
    
    # Convert to a list for output
    cross_referenced_node_ids = list(nodes_in_non_building_ways)
    
    if ways:
        print("Found Way IDs:", [way['id'] for way in ways])
    else:
        print("No ways found within the radius.")
    
    if cross_referenced_node_ids:
        print("Cross-referenced Node IDs (associated with non-building ways):", cross_referenced_node_ids)
    else:
        print("No nodes found in non-building ways.")
else:
    print(f"Request failed with status code {response.status_code}")