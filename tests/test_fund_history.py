import json
import unittest
from unittest.mock import patch

import daily_fund_report as report


API_PAYLOAD = {
    "Data": {
        "LSJZList": [
            {
                "FSRQ": "2026-07-16",
                "DWJZ": "8.0725",
                "LJJZ": "8.3425",
                "JZZZL": "-1.63",
                "SGZT": "闄愬埗澶ч鐢宠喘",
                "SHZT": "寮€鏀捐祹鍥?,
            }
        ]
    },
    "ErrCode": 0,
    "TotalCount": 1,
}


class FundHistoryTests(unittest.TestCase):
    def test_parse_json_history_response(self):
        rows, total_count = report.parse_fund_history_api(json.dumps(API_PAYLOAD))

        self.assertEqual(total_count, 1)
        self.assertEqual(
            rows,
            [
                {
                    "date": "2026-07-16",
                    "nav": 8.0725,
                    "acc_nav": 8.3425,
                    "growth": -1.63,
                    "buy_status": "闄愬埗澶ч鐢宠喘",
                    "sell_status": "寮€鏀捐祹鍥?,
                }
            ],
        )

    def test_fetch_history_falls_back_when_json_source_is_empty(self):
        legacy_response = """
            pages:1
            <table><tr><td>2026-07-16</td><td>8.0725</td><td>8.3425</td>
            <td>-1.63%</td><td>寮€鏀剧敵璐?/td><td>寮€鏀捐祹鍥?/td></tr></table>
        """

        def fake_http_get(url, **_kwargs):
            if url.startswith(report.FUND_HISTORY_API_URL):
                return json.dumps({"Data": {"LSJZList": []}, "ErrCode": 0, "TotalCount": 0})
            return legacy_response

        with patch.object(report, "http_get", side_effect=fake_http_get), patch.object(report.time, "sleep"):
            rows = report.fetch_history("270042", days=1)

        self.assertEqual(rows[0]["date"], "2026-07-16")
        self.assertEqual(rows[0]["nav"], 8.0725)


if __name__ == "__main__":
    unittest.main()

