import ast
from pathlib import Path


SOURCE_PATH = Path(__file__).with_name("scrape.py")


def _source():
    return SOURCE_PATH.read_text(encoding="utf-8")


def _tree():
    return ast.parse(_source())


def test_module_entrypoint_is_last_top_level_runtime_block():
    tree = _tree()

    main_blocks = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    ]

    assert len(main_blocks) == 1

    main_block = main_blocks[0]
    assert main_block is tree.body[-1]

    segment = ast.get_source_segment(_source(), main_block)
    assert segment is not None
    assert "_run_module_entrypoint()" in segment


def test_isolated_dispatch_occurs_after_live_roi_installation():
    source = _source()

    aon_install = source.index(
        "scrape_aon=scrape_aon_live_roi_20260920"
    )
    hcl_install = source.index(
        "scrape_hcltech=scrape_hcltech_live_roi_20260920"
    )
    entrypoint = source.rindex(
        'if __name__ == "__main__":'
    )

    assert entrypoint > aon_install
    assert entrypoint > hcl_install


def test_entrypoint_dispatches_isolated_task_without_running_main():
    source = _source()

    assert "def _run_module_entrypoint():" in source
    assert 'if "--isolated-task" in sys.argv:' in source
    assert "_run_isolated_task_child(task_spec, result_path)" in source
    assert "return\n\n    main()" in source
