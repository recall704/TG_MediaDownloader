IMAGE_NAME=ghcr.io/lightdestory/tg_mediadownloader
VERSION?=v1.0.0

build:
	docker build --network=host -t ${IMAGE_NAME}:${VERSION} .
