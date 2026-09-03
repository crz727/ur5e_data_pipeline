"""Project HDF5 v1 schema shared by the exporter and verifier."""

SCHEMA_NAME = "ur5e_data_pipeline_hdf5"
SCHEMA_VERSION = 1
REQUIRED_VECTOR_FEATURES = {
    "observations/state": (7,),
    "actions": (7,),
}
OPTIONAL_VECTOR_FEATURES = {
    "observations/ee_pose": (7,),
    "observations/joint_velocity": (6,),
    "observations/effort": (6,),
}
REQUIRED_SCALAR_FEATURES = {
    "timestamps": (),
    "frame_index": (),
}
CAMERA_NAMES = ("top", "wrist")


def feature_manifest():
    """Return a JSON-serializable description of the canonical datasets."""
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "layout": "THWC",
        "image_dtype": "uint8",
        "images": {name: "episodes/{episode}/observations/images/" + name for name in CAMERA_NAMES},
        "required": {**{key: list(shape) for key, shape in REQUIRED_VECTOR_FEATURES.items()},
                     **{key: list(shape) for key, shape in REQUIRED_SCALAR_FEATURES.items()},
                     **{f"observations/images/{name}": ["T", "H", "W", 3] for name in CAMERA_NAMES}},
        "optional": {key: list(shape) for key, shape in OPTIONAL_VECTOR_FEATURES.items()},
    }
