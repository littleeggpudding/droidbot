import sys
import argparse
import os
import glob
import csv
from droidbot.utils import generate_html_report


def find_replay_folders():
    """Find all replay_output_*_for_* folders in current directory"""
    current_dir = os.getcwd()
    pattern = os.path.join(current_dir, "replay_output_*_for_*")
    replay_folders = glob.glob(pattern)
    return replay_folders


def derive_record_folder(replay_folder_name):
    """Derive record folder name from replay folder name
    
    Example: replay_output_6_3_0_run3_for_4_7_2 -> record_output_4_7_2_run3
    """
    # Extract the part after "_for_"
    if "_for_" not in replay_folder_name:
        return None
    
    parts = replay_folder_name.split("_for_")
    if len(parts) != 2:
        return None
    
    # Get the version after "_for_"
    target_version = parts[1]
    
    # Find the corresponding record folder
    # Pattern: record_output_{version}_run*
    current_dir = os.getcwd()
    record_pattern = os.path.join(current_dir, f"record_output_{target_version}_run*")
    record_folders = glob.glob(record_pattern)
    
    if record_folders:
        # Return the first match (assuming there's only one)
        return os.path.basename(record_folders[0])
    
    return None


def generate_report_name(replay_folder_name):
    """Generate report folder name by replacing 'replay' with 'report'
    
    Example: replay_output_6_3_0_run3_for_4_7_2 -> report_output_6_3_0_run3_for_4_7_2
    """
    return replay_folder_name.replace("replay_", "report_", 1)


def parse_folder_names(replay_folder_name, record_folder_name):
    """Parse folder names to extract base app, run count, and target app information
    
    Args:
        replay_folder_name: e.g., "replay_output_6_3_0_run3_for_4_7_2"
        record_folder_name: e.g., "record_output_4_7_2_run3"
    
    Returns:
        dict with keys: base_app, run_count, target_app
    """
    # Parse replay folder: replay_output_{base_app}_run{run_count}_for_{target_app}
    replay_parts = replay_folder_name.split("_for_")
    if len(replay_parts) == 2:
        target_app = replay_parts[1]
        base_part = replay_parts[0]
        
        # Extract base app and run count from base_part
        # Format: replay_output_{version}_run{count}
        base_parts = base_part.split("_run")
        if len(base_parts) == 2:
            run_count = base_parts[1]
            # Extract version from replay_output_{version}
            version_part = base_parts[0].replace("replay_output_", "")
            base_app = version_part.replace("_", ".")
        else:
            base_app = "unknown"
            run_count = "unknown"
    else:
        base_app = "unknown"
        target_app = "unknown"
        run_count = "unknown"
    
    return {
        'base_app': base_app,
        'run_count': run_count,
        'target_app': target_app
    }


def batch_analysis():
    """Perform batch analysis on all replay folders"""
    print("Starting batch analysis...")
    
    # Find all replay folders
    replay_folders = find_replay_folders()
    
    if not replay_folders:
        print("No replay_output_*_for_* folders found in current directory.")
        return
    
    print(f"Found {len(replay_folders)} replay folders:")
    for folder in replay_folders:
        print(f"  - {os.path.basename(folder)}")
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    # List to store all analysis results for CSV
    analysis_results = []
    
    for replay_folder in replay_folders:
        replay_name = os.path.basename(replay_folder)
        
        # Derive record folder
        record_name = derive_record_folder(replay_name)
        if not record_name:
            print(f"⚠️  Could not derive record folder for {replay_name}")
            error_count += 1
            continue
        
        # Check if record folder exists
        record_path = os.path.join(os.getcwd(), record_name)
        if not os.path.exists(record_path):
            print(f"⚠️  Record folder not found: {record_name}")
            error_count += 1
            continue
        
        # Generate report name
        report_name = generate_report_name(replay_name)
        report_path = os.path.join(os.getcwd(), report_name)
        
        # Parse folder names to extract information
        folder_info = parse_folder_names(replay_name, record_name)
        
        # Check if report already exists
        if os.path.exists(report_path):
            print(f"⏭️  Skipping {replay_name} - report already exists: {report_name}")
            skipped_count += 1
            # Still add to results even if skipped
            analysis_results.append({
                'base_app': folder_info['base_app'],
                'run_count': folder_info['run_count'],
                'target_app': folder_info['target_app'],
                'report_dir': report_name
            })
            continue
        
        # Generate report
        print(f"🔄 Processing {replay_name} -> {report_name}")
        try:
            # Convert to absolute paths for better performance
            record_path_abs = os.path.abspath(record_path)
            replay_folder_abs = os.path.abspath(replay_folder)
            report_path_abs = os.path.abspath(report_path)
            
            result = generate_html_report(record_path_abs, replay_folder_abs, report_path_abs)
            print(f"✅ Report generated: {result}")
            processed_count += 1
            
            # Add successful result to analysis_results
            analysis_results.append({
                'base_app': folder_info['base_app'],
                'run_count': folder_info['run_count'],
                'target_app': folder_info['target_app'],
                'report_dir': report_name
            })
        except Exception as e:
            print(f"❌ Error processing {replay_name}: {e}")
            error_count += 1
    
    # Generate CSV file
    csv_filename = "batch_analysis_results.csv"
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['base_app', 'run_count', 'target_app', 'report_dir']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for result in analysis_results:
                writer.writerow(result)
        
        print(f"\n📊 CSV report generated: {csv_filename}")
        print(f"   - Total records: {len(analysis_results)}")
    except Exception as e:
        print(f"❌ Error generating CSV: {e}")
    
    print(f"\nBatch analysis completed:")
    print(f"  - Processed: {processed_count}")
    print(f"  - Skipped: {skipped_count}")
    print(f"  - Errors: {error_count}")
    print(f"  - Total: {len(replay_folders)}")


def main():
    parser = argparse.ArgumentParser(description='Generate HTML report for DroidBot test results')
    parser.add_argument('--batch', action='store_true', help='Run batch analysis on all replay folders')
    parser.add_argument('output_dir', nargs='?', help='Directory containing record data (original test output)')
    parser.add_argument('replay_output_dir', nargs='?', help='Directory containing replay data (optional)')
    parser.add_argument('out_dir', nargs='?', help='Output directory for the complete report (HTML + images)')
    
    args = parser.parse_args()
    
    if args.batch:
        batch_analysis()
    else:
        # Single report generation
        if not args.output_dir:
            parser.error("output_dir is required when not using --batch mode")
        
        # Convert to absolute paths for better performance
        output_dir = os.path.abspath(args.output_dir)
        replay_output_dir = os.path.abspath(args.replay_output_dir) if args.replay_output_dir else None
        out_dir = os.path.abspath(args.out_dir) if args.out_dir else None
        
        result = generate_html_report(output_dir, replay_output_dir, out_dir)
        print(f"Report generated successfully: {result}")


if __name__ == "__main__":
    main()