import os
import logging
from typing import List, Dict, Any, Tuple
import pandas as pd
from app.config import settings

logger = logging.getLogger("hubspot_master_service.normalizer")

SUPPORTED_OBJECT_TYPES = ["contacts", "companies", "deals", "tickets", "owners"]


class DataNormalizer:
    """
    Normalizes raw HubSpot JSON object arrays into clean, flat relational DataFrames
    and writes them to local Parquet files for storage upload.
    """

    @staticmethod
    def normalize_records(object_type: str, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Flattens raw JSON objects into a pandas DataFrame.
        """
        if not records:
            return pd.DataFrame()

        rows = []
        for rec in records:
            row: Dict[str, Any] = {}

            if object_type == "owners":
                row["id"] = str(rec.get("id", ""))
                row["email"] = rec.get("email")
                row["first_name"] = rec.get("firstName")
                row["last_name"] = rec.get("lastName")
                row["user_id"] = rec.get("userId")
                row["created_at"] = rec.get("createdAt")
                row["updated_at"] = rec.get("updatedAt")
                row["archived"] = rec.get("archived", False)
                
                # Capture any extra properties
                for k, v in rec.items():
                    if k not in ("id", "email", "firstName", "lastName", "userId", "createdAt", "updatedAt", "archived"):
                        row[f"raw_{k}"] = str(v) if isinstance(v, (dict, list)) else v
            else:
                row["id"] = str(rec.get("id", ""))
                row["created_at"] = rec.get("createdAt")
                row["updated_at"] = rec.get("updatedAt")
                row["archived"] = rec.get("archived", False)

                # Flatten nested properties
                props = rec.get("properties", {})
                if isinstance(props, dict):
                    for p_key, p_val in props.items():
                        # Flatten property keys cleanly
                        row[p_key] = p_val

                # Capture associations summary if present
                associations = rec.get("associations")
                if associations and isinstance(associations, dict):
                    for assoc_type, assoc_data in associations.items():
                        if isinstance(assoc_data, dict) and "results" in assoc_data:
                            assoc_ids = [str(item.get("id")) for item in assoc_data["results"] if item.get("id")]
                            row[f"assoc_{assoc_type}_ids"] = ",".join(assoc_ids)

            rows.append(row)

        df = pd.DataFrame(rows)
        return df

    @classmethod
    def normalize_to_parquet(
        cls,
        object_type: str,
        records: List[Dict[str, Any]],
        output_dir: str,
        scan_id: str
    ) -> Tuple[str, int]:
        """
        Normalizes raw JSON records and writes them as a Parquet file to output_dir.
        Returns: (file_path, record_count)
        """
        os.makedirs(output_dir, exist_ok=True)
        df = cls.normalize_records(object_type, records)

        file_name = f"{object_type}_{scan_id}.parquet"
        file_path = os.path.join(output_dir, file_name)

        if df.empty:
            # Create minimal empty schema DataFrame
            df = pd.DataFrame({"id": pd.Series(dtype="str")})

        # Convert object/mixed columns to string or native JSON-safe types to ensure PyArrow compatibility
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: str(x) if isinstance(x, (dict, list)) else x)

        df.to_parquet(file_path, index=False, engine="pyarrow")
        logger.info(f"Normalized {len(records)} {object_type} records to {file_path}")

        return file_path, len(records)
