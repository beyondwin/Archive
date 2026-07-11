import unittest
import session_store


class SessionIsolationTest(unittest.TestCase):
    def setUp(self):
        session_store._draft.clear()

    def test_drafts_are_owned_by_session(self):
        session_store.save_draft("alpha", "A")
        session_store.save_draft("beta", "B")
        self.assertEqual(session_store.load_draft("alpha"), "A")
        self.assertEqual(session_store.load_draft("beta"), "B")


if __name__ == "__main__":
    unittest.main()
