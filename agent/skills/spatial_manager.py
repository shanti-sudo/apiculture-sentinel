"""
Agent Skill: Apiary Spatial Manager
Purpose: Reusable module to evaluate spatial layout safety and capacity metrics for apiaries.

Requirements & Standards:
- Standard Langstroth Hive Box Footprint: ~1.3 sq. feet (16.25" Width x 19.875" Length).
- Spacing Rules: Minimum 3 feet of working clearance behind and on both sides of each hive; 
                 5 to 10 feet of clear flight path in front of the hive.
- Capacity Formula: Total Sq Ft available / 20 = Maximum number of hives.
"""

CAPACITY_DIVIDER = 20
MIN_FRONT_CLEARANCE = 5.0
MIN_REAR_CLEARANCE = 3.0
MIN_SIDES_CLEARANCE = 3.0

class ApiarySpatialManager:
    """
    Manages apiary layout spatial planning, verifying working space requirements
    and capacity limits.
    """

    def validate_layout(self, layout_data: dict) -> dict:
        """
        Validates the proposed apiary layout clearances and capacity limits.
        
        Args:
            layout_data (dict): Dictionary representing the apiary layout, containing:
                - total_sq_ft (float): Total square footage.
                - num_hives (int): Number of hives (optional/fallback).
                - hives (list): List of dictionaries, each with:
                    - hive_id (str)
                    - clearance_front_ft (float)
                    - clearance_back_ft (float)
                    - clearance_sides_ft (float)
                    
        Returns:
            dict: Compliance report containing status ('COMPLIANT' or 'REJECTED'),
                  compliant_hives count, and detailed list of violations mapped by hive_id.
        """
        total_sq_ft = float(layout_data.get("total_sq_ft", 100.0))
        hives = layout_data.get("hives", [])

        max_hives = int(total_sq_ft // CAPACITY_DIVIDER)

        # If no hives list is provided, fall back to simple capacity-based logic (backward compatibility)
        if not hives:
            num_hives = int(layout_data.get("num_hives", 0))
            compliant = num_hives <= max_hives
            status = "COMPLIANT" if compliant else "REJECTED"
            excess_hives = max(0, num_hives - max_hives)

            violations = []
            if not compliant:
                violations.append({
                    "hive_id": "apiary",
                    "reasons": [f"Hive count {num_hives} exceeds maximum capacity of {max_hives} hives."]
                })

            return {
                "status": status,
                "compliant_hives": min(num_hives, max_hives),
                "violations": violations,
                "compliant": compliant,
                "max_hives": max_hives,
                "excess_hives": excess_hives,
                "total_sq_ft": total_sq_ft,
                "num_hives": num_hives
            }

        violations = []
        compliant_count = 0

        for hive in hives:
            hive_id = hive.get("hive_id", "unknown")
            front = float(hive.get("clearance_front_ft", 0.0))
            back = float(hive.get("clearance_back_ft", 0.0))
            sides = float(hive.get("clearance_sides_ft", 0.0))

            reasons = []
            if front < MIN_FRONT_CLEARANCE:
                reasons.append(f"Front clearance {front:.1f} ft is below the required {MIN_FRONT_CLEARANCE:.1f} ft clear flight path.")
            if back < MIN_REAR_CLEARANCE:
                reasons.append(f"Rear clearance {back:.1f} ft is below the required {MIN_REAR_CLEARANCE:.1f} ft working clearance.")
            if sides < MIN_SIDES_CLEARANCE:
                reasons.append(f"Side clearance {sides:.1f} ft is below the required {MIN_SIDES_CLEARANCE:.1f} ft working clearance.")

            if reasons:
                violations.append({
                    "hive_id": hive_id,
                    "reasons": reasons
                })
            else:
                compliant_count += 1

        num_hives = len(hives)
        capacity_compliant = num_hives <= max_hives
        all_clearances_compliant = len(violations) == 0

        status = "COMPLIANT" if (all_clearances_compliant and capacity_compliant) else "REJECTED"

        if not capacity_compliant:
            violations.append({
                "hive_id": "apiary",
                "reasons": [f"Total hive count {num_hives} exceeds maximum capacity of {max_hives} hives."]
            })

        return {
            "status": status,
            "compliant_hives": compliant_count,
            "violations": violations,
            "compliant": status == "COMPLIANT",
            "max_hives": max_hives,
            "excess_hives": max(0, num_hives - max_hives),
            "total_sq_ft": total_sq_ft,
            "num_hives": num_hives
        }
