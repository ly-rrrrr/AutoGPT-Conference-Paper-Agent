def test_papers_support_search_and_status_filter(client, seeded_db):
    response = client.get(
        "/api/papers",
        params={"query": "vision", "mapping_status": "matched"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["arxiv_id"] == "2607.00001"
    assert response.json()["items"][0]["likes"] == 18


def test_paper_detail_separates_provenance_and_analysis(client, seeded_db):
    paper_id = str(seeded_db["matched"].id)

    response = client.get(f"/api/papers/{paper_id}")

    assert response.status_code == 200
    assert response.json()["authors"] == ["Alice Zhang"]
    assert response.json()["mapping"]["source_path"] == "mappings.jsonl"
    assert response.json()["analysis"]["payload"]["research_problem"].endswith(
        "[page 1]."
    )


def test_unknown_paper_returns_404(client):
    response = client.get("/api/papers/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404

