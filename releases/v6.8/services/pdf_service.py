from __future__ import annotations
from repositories.pdf_repository import PdfRepository
class PdfService:
    def __init__(self,repo:PdfRepository):self.repo=repo
    def list(self,*,limit:int=5000):return self.repo.list(limit=limit)
