

VERSION=$(date +%Y.%m.%d-%H.%M.%S)

echo $VERSION

env VERSION=${VERSION} make build
