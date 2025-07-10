# app/core/identity_resolver.py

import json
import os 
from collections import defaultdict
from typing import Dict, List, Tuple
from filelock import FileLock

# --- Levenshtein Distance for fuzzy matching (no new library needed) ---
def levenshtein_distance(s1, s2):
    s1 = s1.lower()
    s2 = s2.lower()
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

# --- Main Resolution Logic ---

class IdentityStore:
    def __init__(self, store_path="data/identity_store.json", cluster_path="data/clusters.json"):
        self.store_path = store_path
        self.cluster_path = cluster_path
        self.lock = FileLock(f"{self.store_path}.lock")
        self.store = self._load_json(self.store_path)
        self.clusters = self._load_json(self.cluster_path)
        self._pii_lookup = self._build_lookup_index()

    def _load_json(self, path):
        """Safely loads a JSON file, creating it if it doesn't exist."""
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}

    def _build_lookup_index(self):
        """Creates a fast in-memory map of {pii_value: person_id}."""
        lookup = {}
        persons = self.store.get("persons", {})
        for person_id, data in persons.items():
            for pii_type, values in data.items():
                for placeholder, value in values.items():
                    lookup[value] = person_id
        return lookup

    def _get_next_person_id(self):
        """Gets the next available person ID."""
        metadata = self.store.setdefault("_metadata", {})
        last_index = metadata.get("last_person_index", -1)
        next_index = last_index + 1
        metadata["last_person_index"] = next_index
        return f"PERSON_{next_index}"
    
    def resolve_and_update(self, grouped_pii: Dict) -> Dict[str, str]:
        """
        The main function to match, merge, and update the store.
        Returns a map of {original_pii_value: placeholder} for the current document.
        """
        with self.lock:
            # Reload the store inside the lock to get the absolute latest version
            self.store = self._load_json(self.store_path)
            self.clusters = self._load_json(self.cluster_path)
            self._pii_lookup = self._build_lookup_index()

            document_masking_map = {} # {original_pii: placeholder} for this doc

            # Process persons first
            for temp_person_id, pii_data in grouped_pii.get("persons", {}).items():
                matched_person_id = self._find_match(pii_data)
                
                if not matched_person_id:
                    matched_person_id = self._get_next_person_id()
                    self.store.setdefault("persons", {})[matched_person_id] = {}

                # Merge PII and create placeholders for this person
                person_placeholders = self._merge_person_pii(matched_person_id, pii_data)
                document_masking_map.update(person_placeholders)

            # Process unlinked PII
            unlinked_placeholders = self._process_unlinked_pii(grouped_pii.get("unlinked_pii", {}))
            document_masking_map.update(unlinked_placeholders)

            # Save the updated store and clusters back to disk
            self._save_json(self.store_path, self.store)
            self._save_json(self.cluster_path, self.clusters)
        
        return document_masking_map

    def _find_match(self, new_pii_data: Dict) -> str | None:
        """Finds a matching person_id for a new profile using exact and fuzzy matching."""
        # Exact match on high-certainty fields
        for pii_type in ["emails", "phones", "nrics", "ssns"]:
            for value in new_pii_data.get(pii_type, []):
                if value in self._pii_lookup:
                    return self._pii_lookup[value]
        
        # Fuzzy match on names
        for new_name in new_pii_data.get("names", []):
            for existing_person_id, existing_data in self.store.get("persons", {}).items():
                for existing_name in existing_data.get("names", {}).values():
                    if levenshtein_distance(new_name, existing_name) <= 2: # Threshold of 2
                        # Record the cluster/merge
                        self.clusters.setdefault(existing_person_id, []).append(f"Fuzzy matched '{new_name}' with '{existing_name}'")
                        return existing_person_id
        return None

    def _merge_person_pii(self, person_id: str, pii_data: Dict) -> Dict[str, str]:
        """Merges new PII into an existing person's profile and returns placeholders."""
        person_profile = self.store["persons"][person_id]
        placeholders = {}
        
        for pii_type, values in pii_data.items():
            pii_type_plural = pii_type.lower() + "s" # e.g., "name" -> "names"
            
            # Ensure the structure exists
            if pii_type_plural not in person_profile:
                person_profile[pii_type_plural] = {}

            # Get existing values to avoid duplicates
            existing_values = set(person_profile[pii_type_plural].values())
            
            for value in values:
                if value not in existing_values:
                    # Find the next index for this PII type for this person
                    current_index = len(person_profile[pii_type_plural])
                    placeholder = f"[{person_id}_{pii_type.upper()}_{current_index}]"
                    
                    person_profile[pii_type_plural][placeholder] = value
                    self._pii_lookup[value] = person_id # Update live index
                    placeholders[value] = placeholder
        
        return placeholders

    def _process_unlinked_pii(self, unlinked_data: Dict) -> Dict[str, str]:
        """Processes unlinked PII, storing it and returning placeholders."""
        placeholders = {}
        unlinked_store = self.store.setdefault("unlinked_pii", {})
        metadata = self.store.setdefault("_metadata", {})
        counters = metadata.setdefault("unlinked_pii_counters", {})

        for pii_type, values in unlinked_data.items():
            unlinked_store.setdefault(pii_type, {})
            
            for value in values:
                # To avoid re-adding if seen before (less likely but safe)
                if value not in unlinked_store[pii_type].values():
                    current_index = counters.get(pii_type.upper(), 0)
                    placeholder = f"[UNMATCHED_{pii_type.upper()}_{current_index}]"
                    
                    unlinked_store[pii_type][placeholder] = value
                    placeholders[value] = placeholder
                    counters[pii_type.upper()] = current_index + 1

        return placeholders

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)