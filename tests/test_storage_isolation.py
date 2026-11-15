"""A suíte não pode tocar nos arquivos padrão de uma API local.

O conftest aponta GETNET_SESSION_MEMORY_PATH e GETNET_HUMAN_HANDOFF_PATH para
uma pasta temporária antes de importar `app`. Estes testes garantem que os
stores globais e os criados sem caminho explícito usam essa pasta.
"""

import tempfile
from pathlib import Path

from app.human_handoff import HumanHandoffStore
from app.main import handoff_store, session_memory
from app.session_memory import SessionMemory
from tests.conftest import TEST_STATE_DIR

DEFAULT_SESSION_PATH = Path(tempfile.gettempdir()) / "getnet_session_memory.json"
DEFAULT_HANDOFF_PATH = Path(tempfile.gettempdir()) / "getnet_human_handoff.json"


def test_test_state_dir_is_a_dedicated_temporary_directory():
    assert TEST_STATE_DIR.is_dir()
    assert TEST_STATE_DIR.name.startswith("getnet-tests-")


def test_global_stores_use_the_isolated_paths():
    assert session_memory.storage_path.parent == TEST_STATE_DIR
    assert handoff_store.storage_path.parent == TEST_STATE_DIR
    assert session_memory.storage_path != DEFAULT_SESSION_PATH
    assert handoff_store.storage_path != DEFAULT_HANDOFF_PATH


def test_stores_created_without_a_path_also_use_the_isolated_paths():
    assert SessionMemory().storage_path.parent == TEST_STATE_DIR
    assert HumanHandoffStore().storage_path.parent == TEST_STATE_DIR


def test_writes_during_tests_land_in_the_isolated_directory():
    session_memory.add_message(
        user_id="cliente1988",
        session_id="isolation-check",
        message="Qual o status da transação txn1001?",
        response="Aprovada.",
    )

    assert session_memory.storage_path.exists()
    assert session_memory.storage_path.parent == TEST_STATE_DIR
