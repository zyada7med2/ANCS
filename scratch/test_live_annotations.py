import sys
import os
import time

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.ai_agent import ctx, add_gns3_annotation, clear_gns3_annotations
from network_manager.network.gns3 import GNS3Connector

def main():
    ctx.gns3_url = "http://localhost:3080"
    ctx.gns3_project_id = "f0d67775-e2b7-4938-acc1-e30525ed9527" # The open project ID
    ctx._gns3_connector_instance = None
    ctx.refresh_ui_fn = lambda: print("--> refresh_ui_fn() was called!")

    print(f"Starting GNS3 Drawings live integration test against project: {ctx.gns3_project_id}")
    gns3 = ctx.get_gns3_connector()

    # 1. Clear any existing annotations first
    print("\n--- Step 1: Pre-cleaning any old annotations ---")
    clear_res = clear_gns3_annotations("all")
    print(clear_res)

    # 2. Add bounding box around R1 and R2
    print("\n--- Step 2: Drawing shaded rectangle boundary around 'R1' and 'R2' ---")
    rect_res = add_gns3_annotation(
        annotation_type="rectangle",
        target_devices=["R1", "R2"],
        fill_color="rgba(56, 189, 248, 0.12)", # light sky blue transparent fill
        border_color="rgba(56, 189, 248, 0.7)"  # semi-opaque border
    )
    print("Result:", rect_res)

    # 3. Add text label near the area
    print("\n--- Step 3: Drawing text annotation label ---")
    # Let's place it at x=100, y=20 (manual coordinates) or target devices R1/R2
    text_res = add_gns3_annotation(
        annotation_type="text",
        text="ANCS CO-PILOT BACKBONE ZONE",
        x=200,
        y=150,
        width=250,
        height=35,
        border_color="rgba(56, 189, 248, 0.8)"
    )
    print("Result:", text_res)

    # 4. List drawings to verify
    drawings = gns3.get_drawings(ctx.gns3_project_id)
    print(f"\nTotal drawings registered in GNS3: {len(drawings)}")
    for d in drawings:
        print(f"- Drawing ID: {d.get('drawing_id')}, Position: ({d.get('x')}, {d.get('y')})")

    # 5. Hold for user inspection
    wait_time = 10
    print(f"\n--- Step 4: Holding drawings on GNS3 screen for {wait_time} seconds for inspection ---")
    print(">>> GO TO YOUR GNS3 WINDOW NOW TO SEE THE BLUE SHADED ZONE AND TEXT LABEL! <<<")
    for i in range(wait_time, 0, -1):
        print(f"Clearing in {i} seconds...", end="\r")
        time.sleep(1)
    print("\nTime's up!")

    # 6. Delete drawings
    print("\n--- Step 5: Cleaning up annotations ---")
    clear_res_end = clear_gns3_annotations("all")
    print("Result:", clear_res_end)
    print("\n--- Integration Test Completed! ---")

if __name__ == '__main__':
    main()
