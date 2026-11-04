"""Lecture et ecriture du format PCD binaire (sous-ensemble minimal,
compatible PCL) utilise pour les frames LiDAR de ce projet.

Point d'entree unique pour ce format : avant ce module, read_pcd_binary()
etait reimplementee independamment dans scripts/play_pcd_sequence.py et
webui/viz_helpers.py, et write_pcd_binary() dans scripts/pcap_to_pcd.py."""
import numpy as np

_DTYPE_MAP = {("F", 4): "<f4", ("U", 2): "<u2", ("U", 4): "<u4", ("I", 4): "<i4"}


def read_pcd_binary(path):
    with open(path, "rb") as f:
        fields = sizes = types = counts = n_points = None
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("FIELDS"):
                fields = line.split()[1:]
            elif line.startswith("SIZE"):
                sizes = [int(x) for x in line.split()[1:]]
            elif line.startswith("TYPE"):
                types = line.split()[1:]
            elif line.startswith("COUNT"):
                counts = [int(x) for x in line.split()[1:]]
            elif line.startswith("POINTS"):
                n_points = int(line.split()[1])
            elif line.startswith("DATA"):
                break
        data = f.read()

    dt_fields = []
    for name, size, typ, count in zip(fields, sizes, types, counts):
        np_type = _DTYPE_MAP[(typ, size)]
        for c in range(count):
            dt_fields.append((name if count == 1 else f"{name}_{c}", np_type))
    return np.frombuffer(data, dtype=np.dtype(dt_fields), count=n_points)


def write_pcd_binary(path, points, fields):
    """points: tableau (N, len(fields)) — une colonne par nom de `fields`,
    dans le meme ordre. `fields` reste au choix de l'appelant (ex: le jeu de
    colonnes renvoye par velodyne_decoder dans pcap_to_pcd.py) plutot que
    fixe ici, pour que ce module n'ait aucune connaissance du capteur."""
    n = points.shape[0]
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        f"FIELDS {' '.join(fields)}\n"
        f"SIZE {' '.join(['4'] * len(fields))}\n"
        f"TYPE {' '.join(['F'] * len(fields))}\n"
        f"COUNT {' '.join(['1'] * len(fields))}\n"
        f"WIDTH {n}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n"
        "DATA binary\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(np.ascontiguousarray(points, dtype="<f4").tobytes())
