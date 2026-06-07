from onec_conf_doc.metadata.odata import build_odata_fields_payload, odata_entity_type


def test_odata_entity_type() -> None:
    assert odata_entity_type("Catalog", "Номенклатура") == "Catalog_Номенклатура"


def test_build_odata_fields_payload() -> None:
    payload = build_odata_fields_payload(
        "Document",
        "Отпуск",
        attributes=[
            {
                "name": "Организация",
                "type_repr": "CatalogRef.Организации",
                "synonym": "Организация",
                "comment": "",
                "is_required": True,
            }
        ],
        tabular_sections=[
            {
                "name": "Начисления",
                "synonym": "Начисления",
                "comment": "",
                "attributes": [
                    {
                        "name": "Сумма",
                        "type_repr": "xs:decimal",
                        "synonym": "Сумма",
                        "comment": "",
                        "is_required": False,
                    }
                ],
            }
        ],
    )
    assert payload["entity_type"] == "Document_Отпуск"
    assert payload["fields"][0]["name"] == "Организация"
    assert payload["fields"][0]["required"] is True
    assert payload["tabular_sections"][0]["fields"][0]["kind"] == "tabular_attribute"


def test_build_odata_fields_payload_register() -> None:
    payload = build_odata_fields_payload(
        "InformationRegister",
        "КадроваяИсторияСотрудников",
        attributes=[],
        tabular_sections=[],
        dimensions=[
            {
                "name": "Сотрудник",
                "type_repr": "CatalogRef.Сотрудники",
                "synonym": "Сотрудник",
                "comment": "",
                "is_required": False,
            }
        ],
        resources=[
            {
                "name": "Комментарий",
                "type_repr": "xs:string",
                "synonym": "Комментарий",
                "comment": "",
                "is_required": False,
            }
        ],
    )
    assert payload["entity_type"] == "InformationRegister_КадроваяИсторияСотрудников"
    kinds = {f["name"]: f["kind"] for f in payload["fields"]}
    assert kinds["Сотрудник"] == "dimension"
    assert kinds["Комментарий"] == "resource"
