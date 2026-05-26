import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from network_manager.ai_agent import generate_pdf_report

def run_test():
    print("Running generate_pdf_report execution safety test...")
    filename = "test_run_doc.pdf"
    
    try:
        # Run report generation
        result = generate_pdf_report(filename=filename)
        print(f"Result: {result}")
        
        # Assert success response string from tool
        assert "Success" in result or "HTML report generated" in result or "saved" in result
        print("PASS: generate_pdf_report runs successfully.")
        
        # Clean up fallback files if created in user's Downloads folder
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        html_path = os.path.join(downloads_dir, filename.replace(".pdf", ".html"))
        pdf_path = os.path.join(downloads_dir, filename)
        
        if os.path.exists(html_path):
            os.remove(html_path)
            print(f"Cleaned up: {html_path}")
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            print(f"Cleaned up: {pdf_path}")
            
        sys.exit(0)
    except Exception as e:
        print(f"FAIL: generate_pdf_report raised an exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_test()
