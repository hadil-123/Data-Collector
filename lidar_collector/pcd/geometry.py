"""Corrections geometriques partagees entre les outils qui lisent des
frames PCD."""


def invert_ceiling_mount_z(z):
    """Les deux capteurs VLP-32C sont montes au plafond, tete en bas : leur
    axe Z brut pointe donc vers le bas reel. Appliquer cette fonction a la
    colonne z d'une frame PCD fait que "haut" dans le nuage de points
    correspond au vrai haut de la piece.

    Point d'entree unique pour cette correction : avant ce module, elle
    etait appliquee independamment dans webui/viz_helpers.frame_arrays et
    scripts/play_pcd_sequence.py (_swap_frame / estimate_sequence_bounds)."""
    return -z
