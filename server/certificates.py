import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


FILES = ("root-ca.crt", "root-ca.key", "mef.crt", "mef.key", "brk2.crt", "brk2.key")
NOT_BEFORE = datetime(2013, 1, 1, tzinfo=timezone.utc)
NOT_AFTER = datetime(2037, 12, 31, tzinfo=timezone.utc)


def _name(common_name):
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "KR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MTTL Local"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def _write(path, content, mode):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _key_bytes(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def _certificate_bytes(certificate):
    return certificate.public_bytes(serialization.Encoding.PEM)


def generate_certificates(cert_dir):
    destination = Path(cert_dir)
    destination.mkdir(parents=True, exist_ok=True)
    existing = [name for name in FILES if (destination / name).exists()]
    if existing:
        if len(existing) == len(FILES):
            print(f"Certificates already exist in {destination}; nothing changed.")
            return False
        missing = sorted(set(FILES) - set(existing))
        raise RuntimeError(
            "certificate directory is incomplete; refusing to replace the existing CA "
            f"(present: {', '.join(existing)}; missing: {', '.join(missing)})"
        )

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = _name("MTTL Local Root CA")
    root_certificate = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )

    generated = {
        "root-ca.crt": (_certificate_bytes(root_certificate), 0o644),
        "root-ca.key": (_key_bytes(root_key), 0o600),
    }
    for prefix, hostname in (
        ("mef", "mef.onem2m.uplus.co.kr"),
        ("brk2", "brk2.onem2m.uplus.co.kr"),
    ):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(_name(hostname))
            .issuer_name(root_certificate.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(NOT_BEFORE)
            .not_valid_after(NOT_AFTER)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .sign(root_key, hashes.SHA256())
        )
        generated[f"{prefix}.crt"] = (_certificate_bytes(certificate), 0o644)
        generated[f"{prefix}.key"] = (_key_bytes(key), 0o600)

    try:
        for name, (content, mode) in generated.items():
            _write(destination / name, content, mode)
    except Exception:
        for name in FILES:
            try:
                (destination / name).unlink()
            except FileNotFoundError:
                pass
        raise

    print(f"Generated a unique MTTL CA and server certificates in {destination}.")
    return True
