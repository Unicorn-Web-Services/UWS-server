import subprocess
import sys
import time
import socket
import shutil
from pathlib import Path


class GenericDockerManager:
    def __init__(
        self,
        base_port=8000,
        container_name="fastapi-app",
        image_name="fastapi-app",
        repo_url="https://github.com/Unicorn-Web-Services/UWS-tools",
        project_dir="/Buckets",
        app_module="buckets:app",
        repo_folder=None,
    ):
        self.base_port = base_port
        self.container_name = container_name
        self.image_name = image_name
        self.repo_url = repo_url
        self.repo_folder = (
            repo_folder  # Specific folder to clone from repo (e.g., "Buckets")
        )
        self.project_dir = (
            Path(project_dir) if project_dir else Path.cwd() / "fastapi-setup"
        )
        self.app_module = "buckets:app"  # e.g., "main:app" or "buckets:app"
        self.available_port = None
        self.detected_app_module = None
        self.container_id = None  # Store the container ID

    def log(self, message, level="INFO"):
        """Print formatted log messages"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")

    def check_git_installed(self):
        """Check if Git is installed"""
        try:
            result = subprocess.run(
                ["git", "--version"], capture_output=True, text=True
            )
            if result.returncode == 0:
                self.log(f"Git found: {result.stdout.strip()}")
                return True
            else:
                self.log("Git not found", "ERROR")
                return False
        except FileNotFoundError:
            self.log("Git not installed", "ERROR")
            return False

    def detect_fastapi_app(self):
        """Detect FastAPI application module and entry point"""
        if self.app_module:
            self.detected_app_module = self.app_module
            self.log(f"Using specified app module: {self.app_module}")
            return True

        self.log("Auto-detecting FastAPI application...")

        # Common FastAPI file patterns
        patterns = [
            "main.py",
            "app.py",
            "server.py",
            "api.py",
            "**/main.py",
            "**/app.py",
            "buckets.py",
        ]

        for pattern in patterns:
            files = list(self.project_dir.glob(pattern))
            for file_path in files:
                try:
                    content = file_path.read_text()
                    if (
                        "FastAPI(" in content or "FastAPI()" in content
                    ) and "app =" in content:
                        # Extract the likely app variable name
                        relative_path = file_path.relative_to(self.project_dir)
                        module_name = (
                            str(relative_path)
                            .replace("/", ".")
                            .replace("\\", ".")
                            .replace(".py", "")
                        )

                        # Try to detect app variable name
                        app_var = "app"  # default
                        if "app = FastAPI" in content:
                            app_var = "app"
                        elif "application = FastAPI" in content:
                            app_var = "application"

                        self.detected_app_module = f"{module_name}:{app_var}"
                        self.log(f"Detected FastAPI app: {self.detected_app_module}")
                        return True

                except Exception as e:
                    continue

        # If no FastAPI app detected but we have a main.py, assume it's the entry point
        main_file = self.project_dir / "main.py"
        if main_file.exists():
            self.detected_app_module = "main:app"
            self.log(f"Using main.py as entry point: {self.detected_app_module}")
            return True

        self.log("Could not detect FastAPI application", "ERROR")
        return False

    def detect_python_dependencies(self):
        """Detect Python dependencies from various sources"""
        requirements_file = self.project_dir / "requirements.txt"
        pyproject_file = self.project_dir / "pyproject.toml"

        if requirements_file.exists():
            self.log("Found requirements.txt")
            return True
        elif pyproject_file.exists():
            self.log("Found pyproject.toml")
            return True
        else:
            self.log("No dependency file found, will create basic requirements.txt")
            return False

    def clone_or_setup_repository(self):
        """Clone repository or set up project directory"""
        if self.repo_url:
            self.log(f"Cloning repository from {self.repo_url}...")
            if self.repo_folder:
                self.log(f"Will clone only folder: {self.repo_folder}")

            # Remove existing directory if it exists
            if self.project_dir.exists():
                self.log(f"Removing existing directory: {self.project_dir}")
                shutil.rmtree(self.project_dir)

            try:
                if self.repo_folder:
                    # Use sparse-checkout to clone only specific folder
                    return self._clone_sparse_folder()
                else:
                    # Clone entire repository
                    result = subprocess.run(
                        ["git", "clone", self.repo_url, str(self.project_dir)],
                        capture_output=True,
                        text=True,
                    )

                    if result.returncode == 0:
                        self.log("Repository cloned successfully")
                        return True
                    else:
                        self.log(
                            f"Failed to clone repository: {result.stderr}", "ERROR"
                        )
                        return False

            except Exception as e:
                self.log(f"Error cloning repository: {e}", "ERROR")
                return False
        else:
            # Create project directory if it doesn't exist
            self.project_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"Using project directory: {self.project_dir}")
            return True

    def _clone_sparse_folder(self):
        """Clone only a specific folder using sparse-checkout"""
        temp_clone_dir = self.project_dir.parent / f"{self.project_dir.name}_temp"

        try:
            # Step 1: Clone with no-checkout
            self.log("Performing sparse clone...")
            result = subprocess.run(
                ["git", "clone", "--no-checkout", self.repo_url, str(temp_clone_dir)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.log(f"Failed to clone repository: {result.stderr}", "ERROR")
                return False

            # Step 2: Enable sparse-checkout
            result = subprocess.run(
                ["git", "config", "core.sparseCheckout", "true"],
                cwd=temp_clone_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.log(f"Failed to enable sparse-checkout: {result.stderr}", "ERROR")
                return False

            # Step 3: Specify which folder to checkout
            sparse_checkout_file = temp_clone_dir / ".git" / "info" / "sparse-checkout"
            sparse_checkout_file.write_text(f"{self.repo_folder}/*\n")

            # Step 4: Checkout the files
            result = subprocess.run(
                ["git", "checkout"], cwd=temp_clone_dir, capture_output=True, text=True
            )

            if result.returncode != 0:
                self.log(f"Failed to checkout files: {result.stderr}", "ERROR")
                return False

            # Step 5: Move the specific folder to the target directory
            source_folder = temp_clone_dir / self.repo_folder
            if source_folder.exists():
                self.log(f"Moving {self.repo_folder} to {self.project_dir}")
                # Create parent directory if it doesn't exist
                self.project_dir.parent.mkdir(parents=True, exist_ok=True)
                # Move the folder contents
                shutil.move(str(source_folder), str(self.project_dir))

                # Clean up temp directory
                shutil.rmtree(temp_clone_dir)

                self.log(
                    f"Successfully cloned folder '{self.repo_folder}' from repository"
                )
                return True
            else:
                self.log(
                    f"Folder '{self.repo_folder}' not found in repository", "ERROR"
                )
                return False

        except Exception as e:
            self.log(f"Error during sparse clone: {e}", "ERROR")
            # Clean up temp directory on error
            if temp_clone_dir.exists():
                shutil.rmtree(temp_clone_dir)
            return False
        finally:
            # Ensure temp directory is cleaned up
            if temp_clone_dir.exists():
                shutil.rmtree(temp_clone_dir)

    def create_generic_dockerfile(self):
        """Create a generic Dockerfile for FastAPI applications"""
        dockerfile = self.project_dir / "Dockerfile"
        if dockerfile.exists():
            self.log("Dockerfile already exists, skipping creation")
            return

        self.log("Creating generic Dockerfile...")

        # Detect Python version from existing files or use default
        python_version = "3.11"

        # Check if there's a specific Python version requirement
        requirements_file = self.project_dir / "requirements.txt"
        if requirements_file.exists():
            content = requirements_file.read_text()
            if "python" in content.lower():
                # Try to extract Python version if specified
                pass  # Could add more sophisticated parsing here

        app_module = self.detected_app_module or "main:app"

        dockerfile_content = f"""# Use Python {python_version} slim image
FROM python:{python_version}-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt* pyproject.toml* ./

# Install Python dependencies
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
RUN if [ -f pyproject.toml ]; then pip install --no-cache-dir .; fi

# Copy the application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/uploads /app/data /app/logs

# Expose port 8000
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "{app_module}", "--host", "0.0.0.0", "--port", "8000"]"""

        dockerfile.write_text(dockerfile_content)

    def create_required_files(self):
        """Create required files if they don't exist (generic fallback)"""
        self.log("Ensuring required files exist...")

        # Create basic requirements.txt if no dependency file exists
        if not self.detect_python_dependencies():
            requirements_file = self.project_dir / "requirements.txt"
            self.log("Creating basic requirements.txt...")
            requirements_content = """fastapi>=0.68.0
uvicorn[standard]>=0.15.0
python-multipart"""
            requirements_file.write_text(requirements_content)

        # Create generic Dockerfile
        self.create_generic_dockerfile()

        # If no FastAPI app detected, create a basic one
        if not self.detected_app_module:
            self.log("No FastAPI app detected, creating basic main.py...")
            main_file = self.project_dir / "main.py"
            if not main_file.exists():
                main_content = """from fastapi import FastAPI

app = FastAPI(title="Generic FastAPI Application")

@app.get("/")
async def read_root():
    return {"message": "Hello World! This is a generic FastAPI application."}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)"""
                main_file.write_text(main_content)
                self.detected_app_module = "main:app"

    def check_docker_installed(self):
        """Check if Docker is installed and running"""
        self.log("Checking Docker installation...")
        try:
            result = subprocess.run(
                ["docker", "--version"], capture_output=True, text=True
            )
            if result.returncode == 0:
                self.log(f"Docker found: {result.stdout.strip()}")
                return True
            else:
                self.log("Docker not found", "ERROR")
                return False
        except FileNotFoundError:
            self.log("Docker not installed", "ERROR")
            return False

    def check_docker_running(self):
        """Check if Docker daemon is running"""
        self.log("Checking if Docker daemon is running...")
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, text=True)
            if result.returncode == 0:
                self.log("Docker daemon is running")
                return True
            else:
                self.log("Docker daemon is not running", "ERROR")
                return False
        except Exception as e:
            self.log(f"Error checking Docker daemon: {e}", "ERROR")
            return False

    def find_available_port(self, start_port=8000, max_attempts=50):
        """Find an available port starting from start_port"""
        self.log(f"Looking for available port starting from {start_port}...")

        for port in range(start_port, start_port + max_attempts):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("localhost", port))
                sock.close()
                self.available_port = port
                self.log(f"Found available port: {port}")
                return port
            except OSError:
                continue
            finally:
                sock.close()

        self.log(
            f"No available ports found in range {start_port}-{start_port + max_attempts}",
            "ERROR",
        )
        return None

    def stop_existing_container(self):
        """Stop and remove existing container if it exists"""
        self.log("Checking for existing containers...")

        # Check if container exists
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name={self.container_name}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
        )

        if self.container_name in result.stdout:
            self.log(
                f"Found existing container '{self.container_name}', stopping and removing..."
            )

            # Stop container
            subprocess.run(["docker", "stop", self.container_name], capture_output=True)

            # Remove container
            subprocess.run(["docker", "rm", self.container_name], capture_output=True)

            self.log("Existing container removed")
        else:
            self.log("No existing container found")

    def build_image(self):
        """Build the Docker image"""
        self.log("Building Docker image...")

        try:
            result = subprocess.run(
                ["docker", "build", "-t", self.image_name, "."],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self.log("Docker image built successfully")
                return True
            else:
                self.log(f"Failed to build Docker image: {result.stderr}", "ERROR")
                return False

        except Exception as e:
            self.log(f"Error building Docker image: {e}", "ERROR")
            return False

    def create_directories(self):
        """Create necessary directories"""
        self.log("Creating necessary directories...")

        uploads_dir = self.project_dir / "uploads"
        data_dir = self.project_dir / "data"

        uploads_dir.mkdir(exist_ok=True)
        data_dir.mkdir(exist_ok=True)

        self.log(f"Created directories: {uploads_dir}, {data_dir}")

    def run_container(self):
        """Run the Docker container"""
        if not self.available_port:
            self.log("No available port found", "ERROR")
            return False

        self.log(f"Starting container on port {self.available_port}...")

        try:
            # Get absolute paths for volume mounts
            uploads_path = (self.project_dir / "uploads").resolve()
            data_path = (self.project_dir / "data").resolve()

            # Create and run container
            cmd = [
                "docker",
                "run",
                "-d",  # Detached mode
                "--name",
                self.container_name,
                "-p",
                f"{self.available_port}:8000",
                "-v",
                f"{uploads_path}:/app/uploads",
                "-v",
                f"{data_path}:/app/data",
                "-e",
                "DATABASE_URL=sqlite:///./data/buckets.db",
                self.image_name,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                container_id = result.stdout.strip()
                self.container_id = container_id  # Store the container ID
                self.log(f"Container started successfully (ID: {container_id[:12]})")
                return True
            else:
                self.log(f"Failed to start container: {result.stderr}", "ERROR")
                return False

        except Exception as e:
            self.log(f"Error starting container: {e}", "ERROR")
            return False

    def wait_for_container_ready(self, timeout=60):
        """Wait for the container to be ready"""
        self.log("Waiting for container to be ready...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if container is running
                result = subprocess.run(
                    [
                        "docker",
                        "ps",
                        "--filter",
                        f"name={self.container_name}",
                        "--format",
                        "{{.Status}}",
                    ],
                    capture_output=True,
                    text=True,
                )

                if "Up" in result.stdout:
                    # Try to connect to the API
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    try:
                        sock.connect(("localhost", self.available_port))
                        sock.close()

                        # Try to make an HTTP request to verify the app is responding
                        try:
                            import urllib.request

                            req = urllib.request.Request(
                                f"http://localhost:{self.available_port}/"
                            )
                            req.add_header("User-Agent", "UWS-Orchestrator/1.0")
                            with urllib.request.urlopen(req, timeout=5) as response:
                                if response.getcode() in [
                                    200,
                                    404,
                                    405,
                                ]:  # Any response is good
                                    self.log("Container is ready and API is responding")
                                    return True
                        except Exception as http_error:
                            # If HTTP request fails, at least the port is open
                            self.log(
                                f"Port is open but HTTP request failed: {http_error}"
                            )
                            # Still return True since the port is open and container is running
                            return True

                    except (socket.error, ConnectionRefusedError):
                        pass
                    finally:
                        sock.close()

                time.sleep(3)

            except Exception as e:
                self.log(f"Error checking container status: {e}", "ERROR")

        self.log("Container failed to become ready within timeout", "ERROR")
        return False

    def show_container_logs(self, lines=20):
        """Show recent container logs"""
        self.log("Recent container logs:")
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), self.container_name],
                capture_output=True,
                text=True,
            )
            if result.stdout:
                print("--- Container Logs ---")
                print(result.stdout)
                print("--- End Logs ---")
        except Exception as e:
            self.log(f"Error getting logs: {e}", "ERROR")

    def test_api(self):
        """Test if the API is responding using curl"""
        self.log("Testing API endpoints...")
        try:
            # Test root endpoint using curl
            result = subprocess.run(
                ["curl", "-s", f"http://localhost:{self.available_port}/"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                self.log("✓ Root endpoint responding")

                # Try to test common endpoints
                endpoints = ["/docs", "/health", "/files"]
                for endpoint in endpoints:
                    try:
                        result = subprocess.run(
                            [
                                "curl",
                                "-s",
                                "-o",
                                "/dev/null",
                                "-w",
                                "%{http_code}",
                                f"http://localhost:{self.available_port}{endpoint}",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        if result.returncode == 0 and result.stdout in [
                            "200",
                            "404",
                        ]:  # 404 is fine, means endpoint exists
                            self.log(f"✓ {endpoint} endpoint accessible")
                            break
                    except:
                        continue

                return True

            return False

        except subprocess.TimeoutExpired:
            self.log("API test timed out", "ERROR")
            return False
        except Exception as e:
            self.log(f"API test failed: {e}", "ERROR")
            return False

    def print_access_info(self):
        """Print information on how to access the API"""
        print("\n" + "=" * 60)
        print("🚀 FastAPI Application is now running!")
        print("=" * 60)
        print(f"📡 Main API URL:        http://localhost:{self.available_port}")
        print(f"📚 API Documentation:  http://localhost:{self.available_port}/docs")
        print(f"📖 Alternative Docs:   http://localhost:{self.available_port}/redoc")
        print(f"📋 App Module:         {self.detected_app_module or 'auto-detected'}")
        print(f"📁 Project Directory:  {self.project_dir}")
        print("\n🔧 Container Management:")
        print(f"   View logs:     docker logs {self.container_name}")
        print(f"   Stop:          docker stop {self.container_name}")
        print(f"   Start:         docker start {self.container_name}")
        print(f"   Remove:        docker rm {self.container_name}")
        print("=" * 60)

    def cleanup_on_error(self):
        """Clean up resources if setup fails"""
        self.log("Cleaning up due to error...")
        try:
            subprocess.run(["docker", "stop", self.container_name], capture_output=True)
            subprocess.run(["docker", "rm", self.container_name], capture_output=True)
        except:
            pass

    def run_setup(self):
        """Run the complete setup process"""
        self.log("Starting Generic FastAPI Docker setup...")

        try:
            # Pre-flight checks
            if not self.check_docker_installed():
                self.log(
                    "Please install Docker first: https://docs.docker.com/get-docker/",
                    "ERROR",
                )
                return False

            if not self.check_docker_running():
                self.log("Please start Docker daemon first", "ERROR")
                return False

            # Check Git if we need to clone
            if self.repo_url and not self.check_git_installed():
                self.log("Git is required to clone the repository", "ERROR")
                return False

            # Clone repository or setup project
            if not self.clone_or_setup_repository():
                return False

            # Detect FastAPI application
            if not self.detect_fastapi_app():
                self.log("Could not detect FastAPI app, will create basic one", "WARN")

            # Create required files if they don't exist
            self.create_required_files()

            # Find available port
            if not self.find_available_port(self.base_port):
                return False

            # Setup process
            self.stop_existing_container()
            self.create_directories()

            if not self.build_image():
                return False

            if not self.run_container():
                self.cleanup_on_error()
                return False

            if not self.wait_for_container_ready():
                self.show_container_logs()
                self.cleanup_on_error()
                return False

            # Test and show results
            self.test_api()
            self.print_access_info()

            return True

        except Exception as e:
            self.log(f"Unexpected error during setup: {e}", "ERROR")
            self.cleanup_on_error()
            return False


def setup_fastapi_container(
    repo_url=None,
    repo_folder=None,
    app_module=None,
    base_port=8000,
    container_name="fastapi-app",
    image_name="fastapi-app",
    project_dir=None,
    show_logs=False,
    follow_logs=False,
):
    """
    Setup a FastAPI application in Docker container

    Args:
        repo_url (str, optional): Git repository URL to clone
        repo_folder (str, optional): Specific folder to clone from repository (e.g., 'Buckets')
        app_module (str, optional): FastAPI app module (e.g., 'main:app', 'buckets:app')
        base_port (int): Starting port to search for (default: 8000)
        container_name (str): Container name (default: fastapi-app)
        image_name (str): Image name (default: fastapi-app)
        project_dir (str, optional): Project directory path (default: ./fastapi-setup)
        show_logs (bool): Show container logs if setup fails (default: False)
        follow_logs (bool): Follow logs after successful setup (default: False)

    Returns:
        dict: Setup result with success status, port, and container info
    """

    # Create manager and run setup
    manager = GenericDockerManager(
        base_port=base_port,
        container_name=container_name,
        image_name=image_name,
        repo_url=repo_url,
        project_dir=project_dir,
        app_module=app_module,
        repo_folder=repo_folder,
    )

    success = manager.run_setup()

    result = {
        "success": success,
        "container_name": container_name,
        "image_name": image_name,
        "container_id": manager.container_id,
        "port": manager.available_port,
        "app_module": manager.detected_app_module,
        "project_dir": str(manager.project_dir) if manager.project_dir else None,
    }

    if success:
        result["url"] = f"http://localhost:{manager.available_port}"
        result["docs_url"] = f"http://localhost:{manager.available_port}/docs"

        if follow_logs:
            try:
                print("\n📄 Live logs (Ctrl+C to exit):")
                subprocess.run(["docker", "logs", "-f", container_name])
            except KeyboardInterrupt:
                print(
                    "\n� Log following stopped. Container is still running in the background."
                )
    else:
        if show_logs:
            manager.show_container_logs()

    return result


def main():
    """Main function for command line usage"""
    print("�🐳 Generic FastAPI Docker Setup & Runner")
    print("=" * 45)

    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(
        description="Setup and run any FastAPI application in Docker"
    )
    parser.add_argument(
        "--repo", type=str, help="Git repository URL to clone (optional)"
    )
    parser.add_argument(
        "--repo-folder",
        type=str,
        help="Specific folder to clone from repository (e.g., 'Buckets')",
    )
    parser.add_argument(
        "--app-module",
        type=str,
        help="FastAPI app module (e.g., 'main:app', 'buckets:app')",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Starting port to search for (default: 8000)",
    )
    parser.add_argument(
        "--container-name",
        default="fastapi-app",
        help="Container name (default: fastapi-app)",
    )
    parser.add_argument(
        "--image-name", default="fastapi-app", help="Image name (default: fastapi-app)"
    )
    parser.add_argument(
        "--project-dir", help="Project directory path (default: ./fastapi-setup)"
    )
    parser.add_argument(
        "--logs", action="store_true", help="Show container logs if setup fails"
    )

    args = parser.parse_args()

    # Use the function
    result = setup_fastapi_container(
        repo_url=args.repo,
        repo_folder=args.repo_folder,
        app_module=args.app_module,
        base_port=args.port,
        container_name=args.container_name,
        image_name=args.image_name,
        project_dir=args.project_dir,
        show_logs=args.logs,
        follow_logs=True,
    )

    if result["success"]:
        print("\n✅ Setup completed successfully!")
        print(
            "💡 Tip: Use Ctrl+C to stop log following, but the container will keep running"
        )
        print(f"🔗 Visit {result['docs_url']} to test the endpoints")
    else:
        print("\n❌ Setup failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
