import os
import shutil
import tempfile
import pytest
import pandas as pd
from app.normalization.normalizer import DataNormalizer
from app.storage.minio_client import MinIOStorageClient


def test_normalizer_contacts():
    raw_contacts = [
        {
            "id": "101",
            "properties": {"firstname": "Alice", "lastname": "Smith", "email": "alice@example.com"},
            "createdAt": "2023-01-01T00:00:00Z",
            "updatedAt": "2023-01-02T00:00:00Z",
            "archived": False
        },
        {
            "id": "102",
            "properties": {"firstname": "Bob", "lastname": "Jones", "email": "bob@example.com"},
            "createdAt": "2023-01-03T00:00:00Z",
            "updatedAt": "2023-01-04T00:00:00Z",
            "archived": False
        }
    ]

    df = DataNormalizer.normalize_records("contacts", raw_contacts)
    assert len(df) == 2
    assert "firstname" in df.columns
    assert df.iloc[0]["firstname"] == "Alice"
    assert df.iloc[1]["email"] == "bob@example.com"


def test_normalizer_owners():
    raw_owners = [
        {
            "id": "501",
            "email": "owner1@company.com",
            "firstName": "John",
            "lastName": "Owner",
            "userId": 99,
            "createdAt": "2023-01-01T00:00:00Z",
            "updatedAt": "2023-01-01T00:00:00Z",
            "archived": False
        }
    ]

    df = DataNormalizer.normalize_records("owners", raw_owners)
    assert len(df) == 1
    assert df.iloc[0]["email"] == "owner1@company.com"
    assert df.iloc[0]["first_name"] == "John"


def test_normalize_to_parquet():
    tmp_dir = tempfile.mkdtemp()
    try:
        raw_deals = [
            {
                "id": "deal_1",
                "properties": {"dealname": "Big Enterprise Deal", "amount": "50000"},
                "createdAt": "2023-01-01T00:00:00Z",
                "archived": False
            }
        ]

        pq_path, count = DataNormalizer.normalize_to_parquet(
            object_type="deals",
            records=raw_deals,
            output_dir=tmp_dir,
            scan_id="scan_test_1"
        )

        assert os.path.exists(pq_path)
        assert count == 1

        df_read = pd.read_parquet(pq_path)
        assert len(df_read) == 1
        assert df_read.iloc[0]["dealname"] == "Big Enterprise Deal"
    finally:
        shutil.rmtree(tmp_dir)


def test_minio_partitioning_key():
    key = MinIOStorageClient.build_object_key(
        table_name="contacts",
        organization_id="org_alpha",
        processing_date="2026-10-01"
    )
    expected = "hubspot/contacts/glynac_organization_id=org_alpha/processing_date=2026-10-01/contacts.parquet"
    assert key == expected
