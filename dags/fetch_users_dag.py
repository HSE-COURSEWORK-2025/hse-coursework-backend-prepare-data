# dags/fetch_all_users_and_data.py

import os
import json
import requests
from datetime import datetime, timedelta
from airflow.decorators import dag, task
from docker import DockerClient
from docker.errors import DockerException
from airflow.exceptions import AirflowException

AUTH_API_URL = "http://192.168.0.131:8081"
AUTH_API_FETCH_ALL_USERS_PATH = "/auth-api/api/v1/internal/users/get_all_users"

default_args = {
    "owner": "airflow",
    "start_date": datetime(2025, 4, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=60),
}

@dag(
    dag_id="fetch_all_users_and_data",
    default_args=default_args,
    schedule_interval=os.getenv("CRON_SCHEDULE_CHANNEL_DATA_UPDATE", "0 * * * *"),
    catchup=False,
    max_active_runs=1,
    tags=["user_processing"],
)
def fetch_all_users_and_data_dag():
    @task(retries=2)
    def fetch_users():
        """Fetch all users from the authentication API"""
        try:
            url = f"{AUTH_API_URL}{AUTH_API_FETCH_ALL_USERS_PATH}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            users = response.json()
            
            if not users:
                raise AirflowException("No users found in the response")
                
            return users
        except requests.exceptions.RequestException as e:
            raise AirflowException(f"API request failed: {str(e)}")

    @task(retries=2)
    def process_user(user: dict):
        """Process individual user using Docker container"""
        client = DockerClient(base_url='unix://var/run/docker.sock')
        user_json = json.dumps(user)
        
        try:
            container = client.containers.run(
                image="fetch_user_data:latest",
                command=["python3", "run.py", "--user-json", user_json],
                auto_remove=True,
                network_mode="host",
                environment={
                    "AIRFLOW_UID": os.getenv("AIRFLOW_UID", "0"),
                    "PYTHONUNBUFFERED": "1"
                },
                mounts=[
                    # Add mounts here if needed
                    # Mount(source="/host/path", target="/container/path", type="bind")
                ],
                detach=True
            )

            # Stream container logs to Airflow task logs
            for line in container.logs(stream=True, follow=True):
                print(line.strip().decode('utf-8'))

            exit_code = container.wait()['StatusCode']
            if exit_code != 0:
                raise AirflowException(f"Container failed with exit code {exit_code}")

        except DockerException as e:
            raise AirflowException(f"Docker operation failed: {str(e)}")
        finally:
            try:
                container.remove(force=True)
            except:
                pass

        return f"Successfully processed user {user.get('email', 'unknown')}"

    # DAG structure
    users = fetch_users()
    process_user.expand(user=users)

# Instantiate the DAG
dag_instance = fetch_all_users_and_data_dag()