    import osmnx as ox

G = ox.graph_from_place("Bakırköy, Istanbul, Turkey", network_type="drive")

nodes, edges = ox.graph_to_gdfs(G)

print(f"Toplam node: {len(nodes)}")
print(f"Toplam edge: {len(edges)}")
print()
print("Edge sutunlari:", edges.columns.tolist())
print()
print("Ornek edge:")
print(edges[["name", "highway", "length"]].head(10).to_string())

nodes_export = nodes[["y", "x"]].copy()
nodes_export.columns = ["lat", "lon"]
nodes_export.to_csv("data/nodes.csv")

edges_export = edges[["name", "highway", "length"]].copy()
edges_export.index.names = ["u", "v", "key"]
edges_export.to_csv("data/edges.csv")

print(f"\nVeriler data/ klasorune kaydedildi.")
