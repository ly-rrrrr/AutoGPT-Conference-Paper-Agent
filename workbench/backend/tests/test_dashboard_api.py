def test_dashboard_separates_asset_and_result_counts(client, seeded_db):
    response = client.get("/api/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["papers_total"] == 2
    assert data["mappings"] == {"matched": 1, "not_found": 1}
    assert data["analyses"] == {"SUCCESS": 1}
    assert data["likes_success"] == 1
