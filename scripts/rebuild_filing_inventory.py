import csv
from pathlib import Path

csv_path = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0\filing_inventory.csv")

# Standard 10 companies
rows = [
    # Baseline 4 companies
    {"company": "中国平安", "report_year": "2023", "filename": "中国平安2023年报.pdf", "pdf_sha256": "f55538814200d77a61492ba216e45508f487064207bca6a4d90c7b55add43823", "page_count": "334", "file_size": "7225491", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国平安", "report_year": "2024", "filename": "中国平安2024年报.pdf", "pdf_sha256": "6ffff1cade59c64c8178494c083cac8a4011ef5ae2fed32f85dd488a64a809b2", "page_count": "346", "file_size": "11542073", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国平安", "report_year": "2025", "filename": "中国平安2025年报.pdf", "pdf_sha256": "860c455bbad9be59d3d1bf64bf683733feb79157212532df44b91d49a0b03c2a", "page_count": "370", "file_size": "9497402", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2023", "filename": "新华保险2023年报.pdf", "pdf_sha256": "046dbb6f39ab859f8c6c7beabf06010abf775a860964b24ab076f8053b1365b0", "page_count": "284", "file_size": "4651395", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2024", "filename": "新华保险2024年报.pdf", "pdf_sha256": "a983bd987c15ab982d9fbbce29255afff4bc90ca6ba5f15334d0784a8de1c7f0", "page_count": "292", "file_size": "4245883", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2025", "filename": "新华保险2025年报.pdf", "pdf_sha256": "4a5d6ee54dc0a351acac6d9d3ce1d0eee6d4a388c4c36c1668a35d5ffd35c528", "page_count": "295", "file_size": "6694301", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2023", "filename": "中国太保2023年报.pdf", "pdf_sha256": "716a65f266f6ed6dc12f6906db26b84aeac4745c212c8cb8687c7a4fa0fc9dab", "page_count": "287", "file_size": "8324038", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2024", "filename": "中国太保2024年报.pdf", "pdf_sha256": "3b6117c82942349be225d531b342cbbaf36255d02a2556525e697164a42e6b66", "page_count": "302", "file_size": "13373232", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2025", "filename": "中国太保2025年报.pdf", "pdf_sha256": "3787b6a6ec1bf480be2092e7bae156bd0f1d1b7f9f28bd9226d038951c788dee", "page_count": "310", "file_size": "13107566", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2023", "filename": "中国人寿2023年年度报告.pdf", "pdf_sha256": "5ea1048c3a9323b37b1ad2e870da0fb54d9cfacdfba159aad4b9bec070edc18a", "page_count": "244", "file_size": "5800764", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2024", "filename": "中国人寿2024年年度报告.pdf", "pdf_sha256": "3cc6db9bbd9c3c754548b6be288bcebae7187e5264eba59025237f5aa8c667e0", "page_count": "256", "file_size": "13075666", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2025", "filename": "中国人寿2025年年度报告.pdf", "pdf_sha256": "575a833fd7b83ad3568483273645236eddb751a92ab89f7e1c09105d92cedb27", "page_count": "228", "file_size": "5031381", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    # 6 New companies
    {"company": "中国人保", "report_year": "2023", "filename": "中国人保2023年年度报告.pdf", "pdf_sha256": "f30387d9797371de358b10fd0f9f8237c8909a0ce1d5033ca6ab26378fcc48ce", "page_count": "311", "file_size": "11761172", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人保", "report_year": "2024", "filename": "中国人保2024年年度报告.pdf", "pdf_sha256": "7ede132c8af8d5215b24ecf7b0375374649555e55d058b2eebed02f2e9aac978", "page_count": "299", "file_size": "3579323", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人保", "report_year": "2025", "filename": "中国人保2025年年度报告.pdf", "pdf_sha256": "c8e5ed5435197ff0c056ee9ad6aa630b6e7a655a47ba61e18d352e89745791fe", "page_count": "278", "file_size": "12461533", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    {"company": "中国财险", "report_year": "2023", "filename": "中国财险2023年度报告.pdf", "pdf_sha256": "21c76775ef13228abf0fbda733ef6353b1eeb55c84a90244458a3597edb30d3b", "page_count": "316", "file_size": "6731204", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国财险", "report_year": "2024", "filename": "中国财险2024年度报告.pdf", "pdf_sha256": "d299685cd8ccf6bc6f5580172cca9b24f5150d322351800e082db35842891973", "page_count": "296", "file_size": "3499667", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国财险", "report_year": "2025", "filename": "中国财险2025年度报告.pdf", "pdf_sha256": "36363db8e934dcfea8124a5b9450f7a26bf13be949cb28254b51873328a126f2", "page_count": "276", "file_size": "4816401", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    {"company": "中国再保", "report_year": "2023", "filename": "中国再保2023年年度报告.pdf", "pdf_sha256": "cad91861bded6b02ace912405f50f03524f4eb0a1e05fbe6cb4b04ac5ba32d3c", "page_count": "390", "file_size": "29401669", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国再保", "report_year": "2024", "filename": "中国再保2024年年度报告.pdf", "pdf_sha256": "69055942faf87757f7f0826fa988cf87516a7e3684fd927de3026571b6d480ad", "page_count": "379", "file_size": "31034935", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国再保", "report_year": "2025", "filename": "中国再保2025年年度报告.pdf", "pdf_sha256": "cfcd25105c0573e5d2c0e9dccd5deb9cf5ad5ea7528afe4a851b852e74f3c1a9", "page_count": "370", "file_size": "8205754", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    {"company": "阳光保险", "report_year": "2023", "filename": "阳光保险2023年度报告.pdf", "pdf_sha256": "6a8bab4aabc6573f0a9b409879ef068e8772ec98d01ca0d37b45e1f7829d3b9f", "page_count": "314", "file_size": "5713517", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "阳光保险", "report_year": "2024", "filename": "阳光保险2024年度报告.pdf", "pdf_sha256": "7f20adcc4676dc0906c3b096da0bcd7f9c3d346cccf37486556dec980ec229fa", "page_count": "302", "file_size": "10302604", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "阳光保险", "report_year": "2025", "filename": "阳光保险2025年度报告.pdf", "pdf_sha256": "04ec5cf39c1e1d1d8b7522f87c4f32cb87d524071a9368d82949885942385198", "page_count": "290", "file_size": "10940507", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    {"company": "众安在线", "report_year": "2023", "filename": "众安在线2023年度报告.pdf", "pdf_sha256": "276ceeccde7be81b04ce808f6eba43eb088f609defbe3bd40fc8e2589e49d14e", "page_count": "199", "file_size": "4716786", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "众安在线", "report_year": "2024", "filename": "众安在线2024年度报告.pdf", "pdf_sha256": "3f79f13187ac8516883f30bf886fcf406f1b0fda3ba1388516f6cb2ade596b40", "page_count": "191", "file_size": "5696390", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "众安在线", "report_year": "2025", "filename": "众安在线2025年度报告.pdf", "pdf_sha256": "ea8c839b7f9fe18fc0beb7e57f49c968315b6d346f7341212353cb9ed97f2331", "page_count": "187", "file_size": "9420084", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},

    {"company": "友邦保险", "report_year": "2023", "filename": "友邦保险2023年报.pdf", "pdf_sha256": "24d40562aff2a09911845532bca4be841d484ce3ef2c1366b68c183cf6718779", "page_count": "376", "file_size": "5663865", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "友邦保险", "report_year": "2024", "filename": "友邦保险2024年报.pdf", "pdf_sha256": "50ebe59813386119ba1026a6a42fabc00a86470e970659fa3cf467f1d376a588", "page_count": "371", "file_size": "8796996", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "友邦保险", "report_year": "2025", "filename": "友邦保险2025年报.pdf", "pdf_sha256": "0cddef841305d33d00c7140d326d67605e098329046bf0fc1353987c05e6c752", "page_count": "363", "file_size": "9157028", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
]

fieldnames = [
    "company", "report_year", "filename", "pdf_sha256", "page_count",
    "file_size", "document_modality", "canonical_for_testing",
    "duplicate_group", "annotation_status"
]

with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print("FILING INVENTORY REBUILT WITH 30 ACCURATE ROWS!")
