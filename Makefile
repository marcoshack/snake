.PHONY: build run clean

IMAGE_NAME := snake-agent
DOCKER ?= docker

build:
	$(DOCKER) build -t $(IMAGE_NAME) .

run: build
	$(DOCKER) run -v $(PWD)/.env:/app/.env:ro -v $(PWD)/build/output:/app/build/output $(IMAGE_NAME)

clean:
	$(DOCKER) rmi $(IMAGE_NAME) 2>/dev/null || true
