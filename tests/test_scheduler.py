from longbridge2tg.scheduler import ReportScheduler


def test_scheduler_can_start_stop_and_restart():
    async def scenario():
        calls = []

        class Service:
            async def run(self, trigger):
                calls.append(trigger)

        scheduler = ReportScheduler(Service(), ("20:00", "09:30"))
        try:
            scheduler.start()
            assert scheduler.running is True
            assert len(scheduler.next_run_times()) == 2

            scheduler.stop()
            assert scheduler.running is False

            scheduler.start()
            assert scheduler.running is True
            assert len(scheduler.next_run_times()) == 2
        finally:
            scheduler.stop()

        return calls

    assert __import__("asyncio").run(scenario()) == []
