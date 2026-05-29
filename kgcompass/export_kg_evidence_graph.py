import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from knowledge_graph import KnowledgeGraph
from config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, SEARCH_SPACE


def _node_name(node):
    return (
        node.get("name")
        or node.get("path")
        or node.get("id")
        or node.get("signature")
        or ""
    )


def _path_details(path_nodes, path_rels):
    details = []
    for idx, rel in enumerate(path_rels):
        start = path_nodes[idx]
        end = path_nodes[idx + 1]
        details.append(
            {
                "start_node": _node_name(start),
                "end_node": _node_name(end),
                "start_labels": start.get("labels", []),
                "end_labels": end.get("labels", []),
                "start_type": (start.get("labels") or ["unknown"])[0].lower(),
                "end_type": (end.get("labels") or ["unknown"])[0].lower(),
                "type": rel.get("type", "RELATED"),
                "description": rel.get("description", ""),
            }
        )
    return details


_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "because",
    "before",
    "between",
    "cannot",
    "could",
    "does",
    "doesn",
    "during",
    "error",
    "expected",
    "from",
    "have",
    "into",
    "issue",
    "model",
    "models",
    "nested",
    "only",
    "problem",
    "return",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "when",
    "where",
    "while",
    "with",
    "would",
}


def _split_identifier(value):
    if not value:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    tokens = re.split(r"[^A-Za-z0-9]+", spaced)
    return [
        token.lower()
        for token in tokens
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    ]


def _issue_anchor_terms(root_meta):
    text = "\n".join(
        str(root_meta.get(key) or "")
        for key in ("title", "content", "name")
    )
    exact_terms = set()
    for code_span in re.findall(r"`([^`]+)`", text):
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", code_span):
            lowered = token.lower()
            if len(lowered) >= 3:
                exact_terms.add(lowered)
                exact_terms.update(part for part in lowered.split(".") if len(part) >= 3)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if "_" in token or re.search(r"[a-z][A-Z]", token):
            lowered = token.lower()
            if len(lowered) >= 3 and lowered not in _STOPWORDS:
                exact_terms.add(lowered)

    lexical_terms = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        lexical_terms.update(_split_identifier(token))
    lexical_terms.difference_update(_STOPWORDS)
    return exact_terms, lexical_terms


def _candidate_fields(item):
    fields = [
        item.get("name"),
        item.get("signature"),
        item.get("file_path"),
    ]
    for detail in item.get("path_details", []):
        fields.extend(
            [
                detail.get("start_node"),
                detail.get("end_node"),
                detail.get("description"),
            ]
        )
    return [str(field) for field in fields if field]


def _candidate_identifier_terms(fields):
    exact_terms = set()
    lexical_terms = set()
    for field in fields:
        lowered = field.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", lowered):
            if len(token) < 3:
                continue
            exact_terms.add(token)
            exact_terms.update(part for part in token.split(".") if len(part) >= 3)
        lexical_terms.update(_split_identifier(field))
    return exact_terms, lexical_terms


def _is_boilerplate_candidate(item):
    name = (item.get("name") or "").lower()
    file_path = (item.get("file_path") or "").lower()
    base = name.rsplit(".", 1)[-1]
    if file_path.endswith("/__init__.py") or file_path == "__init__.py":
        return True
    if base in {"__all__", "__version__", "__doc__", "__bibtex__", "__citation__"}:
        return True
    if base.startswith("__") and base.endswith("__"):
        return True
    return False


def _rerank_records(records, root_meta):
    issue_exact, issue_terms = _issue_anchor_terms(root_meta)
    for item in records:
        fields = _candidate_fields(item)
        candidate_exact, candidate_terms = _candidate_identifier_terms(fields)
        normalized_text = "\n".join(fields).lower()
        exact_matches = {
            term
            for term in issue_exact
            if term in candidate_exact or re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", normalized_text)
        }
        token_matches = issue_terms.intersection(candidate_terms)
        path_tokens = set(_split_identifier(item.get("file_path") or ""))
        path_matches = issue_terms.intersection(path_tokens)
        evidence = item.setdefault("evidence", {})
        evidence["issue_exact_anchor_matches"] = sorted(exact_matches)
        evidence["issue_token_matches"] = sorted(token_matches)
        evidence["issue_path_token_matches"] = sorted(path_matches)
        evidence["boilerplate_candidate"] = _is_boilerplate_candidate(item)
        item["ranking_key"] = [
            -len(exact_matches),
            -len(path_matches),
            -len(token_matches),
            -int(evidence.get("support", 0)),
            int(evidence.get("distance", 0)),
            0 if evidence.get("anchor_match", False) else 1,
            1 if evidence.get("boilerplate_candidate", False) else 0,
            item.get("file_path") or "",
            int(item.get("start_line") or 0),
            item.get("name") or "",
        ]
    return sorted(records, key=lambda item: item["ranking_key"])


def _run_query(kg):
    query = """
    MATCH (root:Issue {id: 'root'})
    CALL {
      WITH root
      MATCH p = (root)-[:RELATED]-(n)
      WHERE (n:Method OR n:Class)
      RETURN n, p

      UNION
      WITH root
      MATCH p = (root)-[:RELATED]-(a)-[:RELATED]-(n)
      WHERE (n:Method OR n:Class)
        AND (a:File OR a:Class OR a:Issue OR a:Commit OR a:Experience OR a:Documentation)
      RETURN n, p

      UNION
      WITH root
      MATCH p = (root)-[:RELATED]-(a)-[:RELATED]-(b)-[:RELATED]-(n)
      WHERE (n:Method OR n:Class)
        AND (a:File OR a:Class OR a:Issue OR a:Commit OR a:Experience OR a:Documentation)
        AND (b:File OR b:Class OR b:Method OR b:Issue OR b:Commit OR b:Experience OR b:Documentation)
      RETURN n, p

      UNION
      WITH root
      MATCH p = (root)-[:RELATED]-(a)-[:RELATED]-(b)-[:RELATED]-(c)-[:RELATED]-(n)
      WHERE (n:Method OR n:Class)
        AND (a:File OR a:Class OR a:Issue OR a:Commit OR a:Experience OR a:Documentation)
        AND (b:File OR b:Class OR b:Method OR b:Issue OR b:Commit OR b:Experience OR b:Documentation)
        AND (c:File OR c:Class OR c:Method OR c:Issue OR c:Commit OR c:Experience OR c:Documentation)
      RETURN n, p
    }
    WITH n, p
    WHERE NONE(x IN nodes(p) WHERE x:Directory)
      AND (NOT n:Method OR NOT toLower(coalesce(n.name, '')) CONTAINS 'test'
           OR toLower(coalesce(n.name, '')) CONTAINS 'pytest')
    WITH n, p, length(p) AS distance
    WITH n, min(distance) AS min_distance, collect(p) AS paths
    WITH n, min_distance, [p IN paths WHERE length(p) = min_distance] AS shortest_paths
    UNWIND shortest_paths AS sp
    WITH n, min_distance, shortest_paths,
         collect(DISTINCT coalesce(nodes(sp)[1].name, nodes(sp)[1].path, nodes(sp)[1].id, 'root')) AS first_hop_seeds
    WITH n, min_distance, shortest_paths, size(first_hop_seeds) AS support,
         any(p IN shortest_paths WHERE length(p) = 1 OR any(x IN nodes(p) WHERE x:File AND x.path = n.file_path)) AS anchor_match
    UNWIND shortest_paths AS best_path
    WITH n, min_distance, support, anchor_match, best_path
    ORDER BY length(best_path) ASC,
             [x IN nodes(best_path) | coalesce(x.name, x.path, x.id, '')] ASC
    WITH n, min_distance, support, anchor_match, collect(best_path)[0] AS best_path
    RETURN labels(n) AS labels,
           n.name AS name,
           n.signature AS signature,
           n.file_path AS file_path,
           n.start_line AS start_line,
           n.end_line AS end_line,
           n.source_code AS source_code,
           n.doc_string AS doc_string,
           min_distance AS distance,
           support AS support,
           anchor_match AS anchor_match,
           [node IN nodes(best_path) | {
               labels: labels(node),
               name: node.name,
               path: node.path,
               id: node.id,
               signature: node.signature
           }] AS path_nodes,
           [rel IN relationships(best_path) | {
               type: type(rel),
               description: rel.description
           }] AS path_rels
    ORDER BY support DESC,
             min_distance ASC,
             anchor_match DESC,
             coalesce(n.file_path, '') ASC,
             coalesce(n.name, '') ASC
    """
    with kg.driver.session() as session:
        return [dict(record) for record in session.run(query)]


def _root_meta(kg):
    query = """
    MATCH (root:Issue {id: 'root'})
    RETURN root.title AS title,
           root.content AS content,
           root.name AS name,
           root.created_at AS created_at
    """
    with kg.driver.session() as session:
        record = session.run(query).single()
        return dict(record) if record else {}


def _normalize(record):
    labels = record.pop("labels", [])
    path_nodes = record.pop("path_nodes", [])
    path_rels = record.pop("path_rels", [])
    item = {
        "name": record.get("name"),
        "signature": record.get("signature"),
        "file_path": record.get("file_path"),
        "start_line": record.get("start_line"),
        "end_line": record.get("end_line"),
        "source_code": record.get("source_code"),
        "doc_string": record.get("doc_string"),
        "evidence": {
            "support": record.get("support", 0),
            "distance": record.get("distance", 0),
            "anchor_match": bool(record.get("anchor_match", False)),
        },
        "path_details": _path_details(path_nodes, path_rels),
        "ranking_key": [
            -int(record.get("support", 0)),
            int(record.get("distance", 0)),
            0 if record.get("anchor_match", False) else 1,
            record.get("file_path") or "",
            record.get("name") or "",
        ],
    }
    item["entity_type"] = "class" if "Class" in labels else "method"
    return item


def main():
    parser = argparse.ArgumentParser(
        description="Export no-sweep KGCompass evidence-graph retrieval results."
    )
    parser.add_argument("instance_id", help="Instance id used when building the KG")
    parser.add_argument("output_base", help="Output base directory, e.g. runs/kg_verified")
    parser.add_argument("--tag", default="evidence_graph", help="Output subdirectory tag")
    parser.add_argument("--limit", type=int, default=SEARCH_SPACE)
    args = parser.parse_args()

    output_dir = Path(args.output_base) / args.tag
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{args.instance_id}.json"

    kg = KnowledgeGraph(
        NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, args.instance_id, init_embedder=False
    )
    try:
        root_meta = _root_meta(kg)
        records = _rerank_records([_normalize(record) for record in _run_query(kg)], root_meta)
    finally:
        kg.close()

    methods = [item for item in records if item["entity_type"] == "method"][: args.limit]
    classes = [item for item in records if item["entity_type"] == "class"][: args.limit]

    result = {
        "related_entities": {
            "methods": methods,
            "classes": classes,
            "issues": [],
        },
        "artifact_stats": {},
        "kg_params": {
            "retrieval_mode": "evidence_guided_typed_path_search",
            "score": "lexicographic_symbolic_anchor_support_distance_name",
            "uses_embeddings": False,
            "uses_edge_weights": False,
            "uses_discussion_comments": False,
            "tunable_retrieval_parameters": [],
        },
        "run_meta": {
            "instance_id": args.instance_id,
            "active_root": root_meta,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "tag": args.tag,
        },
    }

    with open(output_file, "w") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"Saved: {output_file}")


if __name__ == "__main__":
    main()
