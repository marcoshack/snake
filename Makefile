.PHONY: build run push clean

IMAGE_NAME := snake-agent
REMOTE_IMAGE := ghcr.io/marcoshack/snake:latest
DOCKER ?= docker

build:
	$(DOCKER) build -t $(IMAGE_NAME) -t $(REMOTE_IMAGE) .

run: build
	$(DOCKER) run -v $(PWD)/.env:/app/.env:ro -v $(PWD)/build/output:/app/build/output $(IMAGE_NAME)

push: build
	$(DOCKER) tag $(IMAGE_NAME) $(REMOTE_IMAGE)
	$(DOCKER) push $(REMOTE_IMAGE)

clean:
	$(DOCKER) rmi $(IMAGE_NAME) 2>/dev/null || true
