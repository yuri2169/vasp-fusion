import xml.etree.ElementTree as ET

from vaspfusion.graph.export import to_csv_edges, to_graphml

N = [{"id": 'ENT-1<&"x', "type": "actor", "alerted": True, "score": 0.9, "subject": True},
     {"id": "ip:198.19.0.1", "type": "ip", "label": "198.19.0.1 vpn PA"}]
E = [{"src": "ip:198.19.0.1", "dst": 'ENT-1<&"x', "kind": "announced_from"}]


def test_graphml_is_valid_xml_and_escapes_ids():
    root = ET.fromstring(to_graphml(N, E))
    ns = {"g": root.tag.split("}")[0].strip("{")}
    ids = [n.get("id") for n in root.iter(f"{{{ns['g']}}}node")]
    assert ids == ['ENT-1<&"x', "ip:198.19.0.1"]
    assert len(list(root.iter(f"{{{ns['g']}}}edge"))) == 1
    assert "true" in to_graphml(N, E) and "True" not in to_graphml(N, E)


def test_csv_has_header_and_rows():
    lines = to_csv_edges(E).strip().splitlines()
    assert lines[0].startswith("src,dst,kind") and len(lines) == 2
