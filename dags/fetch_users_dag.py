# dags/fetch_all_users_and_data.py

import os
import json
import requests
from datetime import datetime, timedelta
from airflow.decorators import dag, task
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount
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

    def create_docker_task(user):
        """Create DockerOperator task for each user"""
        user_json = json.dumps(user, ensure_ascii=False)
        
        return DockerOperator(
            task_id=f"process_user_{user['email'].split('@')[0]}",
            image="fetch_users:latest",  # Должно совпадать с именем при сборке
            api_version='auto',
            auto_remove=True,
            docker_url="unix://var/run/docker.sock",
            network_mode="host",
            command=["--user-json", user_json],  # Аргументы для ENTRYPOINT
            environment={
                "AIRFLOW_UID": os.getenv("AIRFLOW_UID", "0"),
                "PYTHONUNBUFFERED": "1"
            },
            mounts=[
                # Добавьте монтирование при необходимости
                # Mount(source="/host/path", target="/container/path", type="bind")
            ],
            retrieve_output=True,
            retrieve_output_path="/tmp/airflow/"
        )

    @task
    def process_users(users):
        """Process all users in parallel"""
        from airflow.operators.python import get_current_context
        context = get_current_context()
        
        for user in users:
            task = create_docker_task(user)
            task.execute(context)

    # Структура DAG
    users = fetch_users()
    process_users(users)

# Инициализация DAG
dag_instance = fetch_all_users_and_data_dag()