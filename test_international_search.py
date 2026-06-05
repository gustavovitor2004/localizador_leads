# -*- coding: utf-8 -*-
import unittest
from fastapi.testclient import TestClient

# Import functions directly from main
from main import (
    app,
    normalize_phone_match,
    eh_telefone_fixo,
    obter_validacao_whatsapp,
    gerar_leads_fallback
)

class TestInternationalSearch(unittest.TestCase):
    
    def test_normalize_phone_match(self):
        # Suffix matching tests for various formats
        self.assertTrue(normalize_phone_match("+1 305 555 1234", "3055551234"))
        self.assertTrue(normalize_phone_match("+44 7911 123456", "7911123456"))
        self.assertTrue(normalize_phone_match("+55 71 99999-9999", "71999999999"))
        self.assertTrue(normalize_phone_match("+55 71 99999-9999", "999999999"))
        self.assertFalse(normalize_phone_match("12345678", "87654321"))
        self.assertFalse(normalize_phone_match(None, "12345678"))

    def test_eh_telefone_fixo(self):
        # International numbers should return False (we do not restrict them to fixed line filters)
        self.assertFalse(eh_telefone_fixo("+1 305 555 1234"))
        self.assertFalse(eh_telefone_fixo("+44 7911 123456"))
        self.assertFalse(eh_telefone_fixo("+49 172 123456"))
        # BR fixed vs mobile tests
        self.assertTrue(eh_telefone_fixo("+55 71 3333-3333"))
        self.assertTrue(eh_telefone_fixo("71 3333-3333"))
        self.assertTrue(eh_telefone_fixo("3333-3333"))
        self.assertFalse(eh_telefone_fixo("+55 71 99999-9999"))
        self.assertFalse(eh_telefone_fixo("99999-9999"))

    def test_obter_validacao_whatsapp(self):
        # International numbers should return "Provável"
        self.assertEqual(obter_validacao_whatsapp("+1 305 555 1234"), "Provável")
        self.assertEqual(obter_validacao_whatsapp("+44 7911 123456"), "Provável")
        self.assertEqual(obter_validacao_whatsapp("+49 172 123456"), "Provável")
        # BR numbers validation
        self.assertEqual(obter_validacao_whatsapp("+55 71 3333-3333"), "Apenas Ligação")
        self.assertEqual(obter_validacao_whatsapp("+55 71 99999-9999"), "Provável")
        # Confirmed via website
        self.assertEqual(obter_validacao_whatsapp("+55 71 3333-3333", wpp_no_site=True), "SIM (Confirmado)")

    def test_gerar_leads_fallback_international(self):
        # Verify fallback leads generation formats for London
        london_leads = gerar_leads_fallback("Pet Shop", "London")
        self.assertTrue(len(london_leads) > 0)
        for lead in london_leads:
            self.assertTrue(lead["telefone"].startswith("+44"))
            self.assertIn("London", lead["endereco"])
            self.assertEqual(lead["validacao_whatsapp"], "Provável")

        # Verify fallback leads generation formats for Miami
        miami_leads = gerar_leads_fallback("Academia", "Miami")
        self.assertTrue(len(miami_leads) > 0)
        for lead in miami_leads:
            self.assertTrue(lead["telefone"].startswith("+1"))
            self.assertIn("Miami", lead["endereco"])
            self.assertEqual(lead["validacao_whatsapp"], "Provável")

    def test_api_buscar_endpoint_fallback(self):
        client = TestClient(app)
        payload = {
            "nicho": "Pet Shop",
            "cidade": "London",
            "user_id": "usr_demo_123",
            "lang": "en"
        }
        # In mock environment, searching without a real GOOGLE_API_KEY triggers fallback
        response = client.post("/api/buscar", json=payload)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn("leads", data)
        self.assertTrue(len(data["leads"]) > 0)
        self.assertIn("total_analisados", data)
        self.assertEqual(data["api_utilizada"], "Mock Fallback Server-Side Engine")
        
        first_lead = data["leads"][0]
        self.assertTrue(first_lead["telefone"].startswith("+44"))
        self.assertIn("London", first_lead["endereco"])
        self.assertEqual(first_lead["validacao_whatsapp"], "Provável")

if __name__ == "__main__":
    unittest.main()
