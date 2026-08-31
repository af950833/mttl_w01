import os
import sys


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "generate-certs":
        from .certificates import generate_certificates

        try:
            generate_certificates(os.getenv("MTTL_CERT_DIR", "/certs"))
        except (OSError, RuntimeError, ValueError) as error:
            raise SystemExit(f"certificate generation failed: {error}") from error
    elif len(sys.argv) == 1:
        from .app import main

        main()
    else:
        raise SystemExit("usage: python -m server [generate-certs]")
