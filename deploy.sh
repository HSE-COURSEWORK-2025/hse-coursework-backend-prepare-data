#!/usr/bin/env bash

export $(cat .env.prod | sed 's/#.*//g' | xargs) || true

sudo rm -rf docker_data

eval $(minikube docker-env)

docker build -t preprocess_data:latest -f dockerfile.dag .

eval $(minikube docker-env --unset)
