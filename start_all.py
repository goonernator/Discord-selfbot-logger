#!/usr/bin/env python3
"""
Discord Selfbot Logger - Launcher Script
Starts both the web server and Discord client simultaneously.
"""

import subprocess
import sys
import time
import os
from pathlib import Path

def main():
    """Start both web server and Discord client processes."""
    print("="*60)
    print("Discord Selfbot Logger - Starting All Services")
    print("="*60)
    
    # Get the current directory
    current_dir = Path(__file__).parent
    
    # Define the scripts to run
    web_server_script = current_dir / "start_web_server.py"
    discord_client_script = current_dir / "main.py"
    
    # Check if scripts exist
    if not web_server_script.exists():
        print(f"ERROR: Web server script not found: {web_server_script}")
        return 1
    
    if not discord_client_script.exists():
        print(f"ERROR: Discord client script not found: {discord_client_script}")
        return 1
    
    processes = []
    
    try:
        # Start web server
        print("Starting web server...")
        web_process = subprocess.Popen(
            [sys.executable, str(web_server_script)],
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        processes.append(("Web Server", web_process))
        
        # Wait a moment for web server to start
        time.sleep(3)
        
        # Start Discord client
        print("Starting Discord client...")
        discord_process = subprocess.Popen(
            [sys.executable, str(discord_client_script)],
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        processes.append(("Discord Client", discord_process))
        
        print("\n" + "="*60)
        print("Both services started successfully!")
        print("Web Dashboard: http://127.0.0.1:5002")
        print("Press Ctrl+C to stop all services")
        print("="*60 + "\n")
        
        # Monitor processes
        while True:
            time.sleep(1)
            
            # Check if any process has died
            for name, process in processes:
                if process.poll() is not None:
                    print(f"\nWARNING: {name} process has stopped (exit code: {process.returncode})")
                    
                    # Try to read any remaining output
                    try:
                        output = process.stdout.read()
                        if output:
                            print(f"{name} output: {output}")
                    except:
                        pass
    
    except KeyboardInterrupt:
        print("\n\nShutting down all services...")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        
    finally:
        # Clean up processes
        for name, process in processes:
            if process.poll() is None:
                print(f"Stopping {name}...")
                try:
                    process.terminate()
                    # Wait up to 5 seconds for graceful shutdown
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"Force killing {name}...")
                    process.kill()
                except Exception as e:
                    print(f"Error stopping {name}: {e}")
        
        print("All services stopped.")
        return 0

if __name__ == "__main__":
    sys.exit(main())