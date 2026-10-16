# Gefjon 构建入口。
#
# 产物是单一静态二进制：CGO_ENABLED=0（无 libc 依赖，可直接拷进容器/嵌入项目），
# -trimpath 去掉构建路径，-s -w 去掉符号表与调试信息以缩小体积。
#
# 注意：Windows 上没有 make，可直接用等价的 go build：
#   go build -trimpath -ldflags "-s -w" -o gefjon.exe ./cmd/gefjon

BINARY  := gefjon
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo 0.2.0-dev)
COMMIT  ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
DATE    ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)

MODULE  := github.com/Athenavi/Gefjon
LDFLAGS := -s -w \
	-X $(MODULE)/internal/version.Version=$(VERSION) \
	-X $(MODULE)/internal/version.Commit=$(COMMIT) \
	-X $(MODULE)/internal/version.BuildDate=$(DATE)

PLATFORMS := linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64 windows/arm64

.PHONY: all build test vet fmt cross size clean

all: vet test build

build:
	CGO_ENABLED=0 go build -trimpath -ldflags "$(LDFLAGS)" -o $(BINARY) ./cmd/gefjon

test:
	go test ./...

vet:
	go vet ./...

fmt:
	gofmt -l -w .

# 交叉编译出全部平台，并打印体积
cross:
	@mkdir -p dist
	@for platform in $(PLATFORMS); do \
		os=$${platform%/*}; arch=$${platform#*/}; \
		out=dist/$(BINARY)_$${os}_$${arch}; \
		if [ "$$os" = "windows" ]; then out=$$out.exe; fi; \
		echo "building $$out"; \
		CGO_ENABLED=0 GOOS=$$os GOARCH=$$arch go build -trimpath -ldflags "$(LDFLAGS)" -o $$out ./cmd/gefjon || exit 1; \
	done
	@ls -lh dist

size: build
	@ls -lh $(BINARY)

clean:
	rm -rf dist $(BINARY) $(BINARY).exe
