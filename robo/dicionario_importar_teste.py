"""
Teste offline do importador (02/11/2026): sem rede, sem Portal. Roda com:  python robo/dicionario_importar_teste.py
Prova que o modo `importar` confere um lote com a mesma conferir/arrumar do caminho antigo, no modo SO_CONFERIR não posta nada,
e que o relatório fila/rejeitados.json traz o motivo exato.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dicionario as d  # noqa: E402

BOM = {
    "conceito": "Prazo final para entregar uma tarefa, um relatório ou um projeto.",
    "traducoes": ["prazo", "data limite"],
    "nivel": "B1",
    "registro": "neutro",
    "areas": ["Negócios"],
    "sentidos": [{"classe": "noun", "definicao": "Data ou hora limite para terminar algo.", "exemplo": "The deadline for the report is Friday.", "exemploPt": "O prazo do relatório é sexta-feira."}],
    "collocations": [{"expressao": "meet a deadline", "traducao": "cumprir um prazo"}],
    "padroes": [{"padrao": "deadline for + noun", "exemplo": "The deadline for the proposal is tomorrow.", "traducao": "O prazo da proposta é amanhã."}],
    "frases": [{"en": "We missed the deadline by two days.", "pt": "Perdemos o prazo por dois dias."}],
    "alternativas": [{"palavra": "due date", "diferenca": "Due date é a data marcada; deadline é o limite que não pode ser passado."}],
    "relacionados": ["schedule", "milestone"],
    "phrasalVerbs": [],
    "idioms": [{"expressao": "beat the deadline", "significado": "Terminar antes do prazo."}],
    "erroComum": "Brasileiros dizem 'dead line' separado; o certo é 'deadline', uma palavra só.",
    "intencoes": ["cobrar um prazo da equipe"],
}
PENDENTES = {"verbetes": [
    {"id": "ok1", "lema": "deadline", "tipo": "PALAVRA", "base": {"traducoes": ["prazo"], "classes": ["noun"]}},
    {"id": "ruim1", "lema": "deadline", "tipo": "PALAVRA", "base": {}},
    {"id": "ruim2", "lema": "deadline", "tipo": "PALAVRA", "base": {}},
    {"id": "ruim3", "lema": "deadline", "tipo": "PALAVRA", "base": {}},
    {"id": "solto1", "lema": "budget", "tipo": "PALAVRA", "base": {}},
]}


def main():
    ruim_exemplo = json.loads(json.dumps(BOM))
    ruim_exemplo["sentidos"][0]["exemplo"] = "She comes from Brazil."  # não usa a palavra
    ruim_frase = json.loads(json.dumps(BOM))
    ruim_frase["frases"].append({"en": "Our team works hard.", "pt": "Nossa equipe trabalha duro."})
    ruim_formato = json.loads(json.dumps(BOM))
    ruim_formato["nivel"] = "D1"
    ruim_formato["conceito"] = ""
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "verbetes"))
        json.dump(PENDENTES, open(os.path.join(tmp, "pendentes.json"), "w"))
        json.dump([{"id": "ok1", "verbete": BOM}, {"id": "ruim1", "verbete": ruim_exemplo}, {"id": "ruim2", "verbete": ruim_formato}, {"id": "ruim3", "verbete": ruim_frase}, {"id": "solto1", "verbete": None}],
                  open(os.path.join(tmp, "verbetes", "lote-001.json"), "w"))
        os.environ["FILA_DIR"] = tmp
        os.environ["SO_CONFERIR"] = "1"
        chamadas = []
        d.portal = lambda *a, **k: chamadas.append(a) or (_ for _ in ()).throw(AssertionError("SO_CONFERIR não pode chamar o Portal"))
        r = d.fazer_importar()
        assert chamadas == [], chamadas
        assert [x["id"] for x in r["aceitos"]] == ["ok1"], r["aceitos"]
        assert sorted(x["id"] for x in r["rejeitados"]) == ["ruim1", "ruim2", "ruim3"], r["rejeitados"]
        rel = json.load(open(os.path.join(tmp, "rejeitados.json")))
        assert rel["ensaio"] is True
        por_id = {x["id"]: x for x in rel["rejeitados"]}
        assert any("nenhum sentido com exemplo que use a palavra" in m for m in por_id["ruim1"]["motivos"]), por_id["ruim1"]
        assert any("frases: 'Our team works hard.'" in m for m in por_id["ruim3"]["motivos"]), por_id["ruim3"]
        assert any("conceito: obrigatório" in m for m in por_id["ruim2"]["motivos"]) and any("nivel: 'D1'" in m for m in por_id["ruim2"]["motivos"])
        assert not os.path.exists(os.path.join(tmp, "importados.json")), "ensaio não grava importados.json"

        # Modo real com Portal falso: o aceito é enviado, o importado é lembrado e não é reenviado.
        os.environ["SO_CONFERIR"] = ""
        enviados = []

        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ok": True, "resultado": "ok"}

        d.portal = lambda m, c, corpo=None, **k: enviados.append((c, corpo)) or R()
        r = d.fazer_importar()
        ids = [c[1]["id"] for c in enviados]
        assert ids == ["ok1", "solto1"], ids  # ok1 gravado; solto1 = liberação (só id)
        assert "verbete" not in enviados[1][1]
        enviados.clear()
        r = d.fazer_importar()
        assert [c[1]["id"] for c in enviados] == ["solto1"], enviados  # ok1 já importado; liberação repete (inofensivo)
    print("OK: importador confere, recusa com motivo exato, ensaio não posta, importados não repetem.")


if __name__ == "__main__":
    main()
