import asyncio
import json
import sys

from prisma.models import AgentGraph

from backend.data import db
from backend.data.execution import get_graph_executions
from backend.data.graph import get_graph
from backend.executor.utils import add_graph_execution, stop_graph_execution


async def resolve_graph(request):
    user = request.get('user_id')
    graph_id = request.get('graph_id')
    if user and graph_id:
        return user, graph_id
    if user or graph_id:
        raise ValueError('PAPER_USER_ID 和 PAPER_GRAPH_ID 必须同时设置')
    rows = await AgentGraph.prisma().find_many(
        where={'name': 'Conference Paper Research Agent', 'isActive': True},
        order={'version': 'desc'},
        take=20,
    )
    graphs = {}
    for row in rows:
        graphs.setdefault(row.id, row)
    if len(graphs) == 1:
        graph = next(iter(graphs.values()))
        return graph.userId, graph.id
    used = []
    for graph in graphs.values():
        runs = await get_graph_executions(
            user_id=graph.userId,
            graph_id=graph.id,
            limit=1,
        )
        if runs:
            used.append((str(runs[0].started_at or ''), graph))
    if used:
        graph = max(used, key=lambda item: item[0])[1]
        return graph.userId, graph.id
    if len(graphs) != 1:
        raise ValueError(
            '无法唯一识别 Conference Paper Research Agent；'
            '请设置 PAPER_USER_ID 和 PAPER_GRAPH_ID'
        )


async def main(request):
    await db.connect()
    try:
        user, graph_id = await resolve_graph(request)
        graph = await get_graph(graph_id, None, user_id=user)
        if graph is None:
            raise ValueError('找不到已配置的论文工作流')
        runs = await get_graph_executions(user_id=user, graph_id=graph_id, limit=20)
        active = [r for r in runs if str(r.status) in ('RUNNING', 'QUEUED')]
        action = request['action']
        if action == 'start':
            if active:
                raise ValueError('已有任务运行或排队，请等待完成或先停止')
            config = next(n.input_default['value'].copy() for n in graph.nodes if n.input_default.get('name') == 'config')
            config.update(request['config'])
            if config.get('conference') != 'ECCV':
                raise ValueError('当前入口仅支持 ECCV')
            run = await add_graph_execution(graph_id=graph_id, user_id=user, inputs={'config': config}, graph_version=graph.version)
            result = {'message': '任务已提交', 'execution_id': run.id}
        elif action == 'stop':
            for run in active:
                await stop_graph_execution(user, run.id)
            result = {'message': '已发送停止请求，已保存结果保留'}
        else:
            result = {'runs': [{'id': r.id, 'status': str(r.status)} for r in runs]}
        print('CONSOLE_RESULT=' + json.dumps(result, ensure_ascii=False))
    finally:
        await db.disconnect()


if __name__ == '__main__':
    asyncio.run(main(json.loads(sys.argv[1])))
