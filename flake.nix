{
    inputs = {
        nixpkgs.url = "https://flakehub.com/f/NixOS/nixpkgs/*.tar.gz";
        nixpkgs-unstable-small.url = "github:NixOS/nixpkgs/nixos-unstable-small"; #TODO(https://nixpk.gs/pr-tracker.html?pr=524985) ride release train
    };
    outputs = attrs: let
        supportedSystems = [
            "aarch64-darwin"
            "aarch64-linux"
            "x86_64-darwin"
            "x86_64-linux"
        ];
        forEachSupportedSystem = f: attrs.nixpkgs.lib.genAttrs supportedSystems (system: f {
            pkgs = import attrs.nixpkgs {
                inherit system;
            };
            pkgs-unstable-small = import attrs.nixpkgs-unstable-small {
                inherit system;
            };
        });
    in {
        packages = forEachSupportedSystem ({ pkgs, pkgs-unstable-small, ... }: let
            manifest = (pkgs.lib.importTOML ./Cargo.toml).workspace.package;
        in {
            default = pkgs-unstable-small.rustPlatform.buildRustPackage {
                pname = "gefolge-web";
                version = manifest.version;
                buildAndTestSubdir = "crate/front";
                buildInputs = with pkgs; [
                    openssl
                ];
                buildNoDefaultFeatures = true;
                cargoLock = {
                    allowBuiltinFetchGit = true; # provides access to private crates on fenhl.net, and allows omitting cargoLock.outputHashes
                    lockFile = ./Cargo.lock;
                };
                nativeBuildInputs = with pkgs; [
                    pkg-config
                ];
                src = ./.;
            };
        });
    };
}
