"""API server to serve all FineHance data to the Vite frontend."""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

DATA_DIR = os.path.join(os.path.dirname(__file__), '../data')
PORT = 8787

FILES = {
    'expenses': 'expenses.json',
    'wallets': 'wallets.json',
    'budgets': 'budgets.json',
    'ledger': 'ledger.json',
    'gamification': 'gamification.json',
}


def _load(name):
    path = os.path.join(DATA_DIR, FILES.get(name, ''))
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, status=200):
        body = json.dumps(data)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(body.encode())

    def _user_param(self):
        if '?user=' in self.path:
            return self.path.split('?user=')[1].split('&')[0]
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        user = self._user_param()

        if path == '/api/expenses':
            data = _load('expenses')
            self._json(data.get(user, []) if user else data)

        elif path == '/api/wallets':
            data = _load('wallets')
            self._json(data.get(user, {}) if user else data)

        elif path == '/api/budgets':
            data = _load('budgets')
            self._json(data.get(user, {}) if user else data)

        elif path == '/api/ledger':
            data = _load('ledger')
            self._json(data.get(user, []) if user else data)

        elif path == '/api/gamification':
            data = _load('gamification')
            self._json(data.get(user, {}) if user else data)

        elif path == '/api/all':
            # Single call to get everything for a user — ideal for dashboard
            if not user:
                self._json({"error": "user param required"}, 400)
                return
            self._json({
                "expenses": _load('expenses').get(user, []),
                "wallets": _load('wallets').get(user, {}),
                "budgets": _load('budgets').get(user, {}),
                "ledger": _load('ledger').get(user, []),
                "gamification": _load('gamification').get(user, {}),
            })

        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    print(f"API server running on http://localhost:{PORT}")
    print("Endpoints: /api/expenses, /api/wallets, /api/budgets, /api/ledger, /api/gamification, /api/all")
    print("Add ?user=USER_ID to filter by user")
    HTTPServer(('', PORT), Handler).serve_forever()
