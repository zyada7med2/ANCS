"""
Vendor profile registry for ANCS.

Provides ``get_profile(vendor_id)`` to obtain a concrete VendorProfile, and
``detect_vendor(gns3_node)`` to auto-detect the vendor from GNS3 node metadata.
"""
from __future__ import annotations

from .base import SessionConfig, VendorProfile
from .cisco_ios import CiscoIOSProfile
from .huawei_vrp import HuaweiVRPProfile

VENDOR_REGISTRY: dict[str, type[VendorProfile]] = {
    "cisco_ios": CiscoIOSProfile,
    "huawei_vrp": HuaweiVRPProfile,
}

_DEFAULT_VENDOR = "cisco_ios"


def get_profile(vendor_id: str) -> VendorProfile:
    """Return an instantiated VendorProfile for *vendor_id* (falls back to Cisco)."""
    cls = VENDOR_REGISTRY.get(vendor_id, VENDOR_REGISTRY[_DEFAULT_VENDOR])
    return cls()


def detect_vendor(gns3_node: dict) -> str:
    """Auto-detect vendor_id from GNS3 node metadata. Returns a vendor_id string."""
    raw_type = gns3_node.get("node_type", "")
    platform = gns3_node.get("platform", "")
    image_name = (gns3_node.get("properties") or {}).get("image", "")
    name = gns3_node.get("name", "")
    full_desc = " ".join([raw_type, platform, image_name, name]).lower()

    for vid, cls in VENDOR_REGISTRY.items():
        if vid == _DEFAULT_VENDOR:
            continue
        profile = cls()
        kw = profile.gns3_detection_keywords()
        for kw_list in kw.values():
            if any(k in full_desc for k in kw_list):
                return vid
    return _DEFAULT_VENDOR
