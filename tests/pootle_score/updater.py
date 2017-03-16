# -*- coding: utf-8 -*-
#
# Copyright (C) Pootle contributors.
#
# This file is a part of the Pootle project. It is distributed under the GPL3
# or later license. See the LICENSE file for a copy of the license and the
# AUTHORS file for copyright and authorship information.

from datetime import date, datetime, timedelta

import pytest

from django.utils.functional import cached_property

from pootle.core.delegate import event_score, score_updater
from pootle.core.plugin import provider
from pootle.core.plugin.results import GatheredDict
from pootle.core.utils.timezone import make_aware
from pootle_log.utils import LogEvent, StoreLog
from pootle_score.models import UserStoreScore
from pootle_score.updater import StoreScoreUpdater
from pootle_store.models import Store


@pytest.mark.django_db
def test_score_store_updater(store0, admin):
    updater = score_updater.get(Store)(store=store0)
    assert updater.store == store0
    assert updater.user is None
    assert isinstance(updater, StoreScoreUpdater)
    assert isinstance(updater.logs, StoreLog)
    assert updater.event_class == LogEvent
    assert isinstance(updater.scoring, GatheredDict)
    updater = score_updater.get(Store)(store=store0, user=admin)
    assert updater.user == admin


@pytest.mark.django_db
def test_score_store_updater_event(store0, admin, member):
    unit0 = store0.units[0]
    unit1 = store0.units[1]
    today = date.today()
    yesterday = today - timedelta(days=1)

    class DummyLogs(object):
        _start = None
        _end = None
        _user = None

        @property
        def _events(self):
            return [
                LogEvent(unit0, admin, today, "action0", 0),
                LogEvent(unit0, admin, yesterday, "action1", 1),
                LogEvent(unit1, member, today, "action2", 2)]

        def get_events(self, start=None, end=None, user=None, **kwargs):
            self._start = start
            self._end = end
            self._user = user
            for event in self._events:
                yield event

    class DummyScoreUpdater(StoreScoreUpdater):

        @cached_property
        def logs(self):
            return DummyLogs()

    updater = DummyScoreUpdater(store=store0)
    result = updater.calculate()
    assert updater.logs._start == make_aware(
        datetime.combine(today, datetime.min.time()))
    assert updater.logs._end is None
    assert updater.logs._user is None
    # no score adapters
    assert result == {}
    result = updater.calculate(start=yesterday, end=today)
    assert updater.logs._start == yesterday
    assert updater.logs._end == today
    assert result == {}
    updater = DummyScoreUpdater(store=store0, user=admin)
    updater.calculate()
    assert updater.logs._user == admin


@pytest.mark.django_db
def test_score_store_updater_event_score(store0, admin, member, member2):
    unit0 = store0.units[0]
    unit1 = store0.units[1]
    today = date.today()
    yesterday = today - timedelta(days=1)

    class DummyLogs(object):
        _start = None
        _end = None

        @cached_property
        def _events(self):
            return [
                LogEvent(unit0, admin, yesterday, "action0", 0),
                LogEvent(unit0, admin, yesterday, "action1", 1),
                LogEvent(unit0, admin, today, "action0", 0),
                LogEvent(unit0, member2, today, "action1", 1),
                LogEvent(unit0, member, today, "action2", 2),
                LogEvent(unit1, member, today, "action2", 3)]

        def get_events(self, start=None, end=None, **kwargs):
            self._start = start
            self._end = end
            for event in self._events:
                yield event

    class DummyScoreUpdater(StoreScoreUpdater):

        @cached_property
        def logs(self):
            return DummyLogs()

    updater = DummyScoreUpdater(store=store0)
    result = updater.calculate()
    assert result == {}

    class DummyScore(object):

        def __init__(self, event):
            self.event = event

        def get_score(self):
            return dict(
                score=(self.event.value * self.base_score),
                translated=(7 * self.base_score),
                reviewed=(23 * self.base_score),
                suggested=(108 * self.base_score))

    class Action0Score(DummyScore):
        base_score = 0

    class Action1Score(DummyScore):
        base_score = 1

    class Action2Score(DummyScore):
        base_score = 2

        def get_score(self):
            score = super(Action2Score, self).get_score()
            score["reviewed"] = 0
            return score

    @provider(event_score, sender=LogEvent)
    def dummy_event_score_provider(**kwargs_):
        return dict(
            action0=Action0Score,
            action1=Action1Score,
            action2=Action2Score)

    updater = DummyScoreUpdater(store=store0)
    result = updater.calculate()
    assert len(result) == 2
    assert len(result[today]) == 2
    assert result[today][member.id] == {
        'suggested': 432,
        'score': 10,
        'translated': 28}
    assert result[today][member2.id] == {
        'suggested': 108,
        'score': 1,
        'translated': 7,
        'reviewed': 23}
    assert len(result[yesterday]) == 1
    assert result[yesterday][admin.id] == {
        'suggested': 108,
        'score': 1,
        'translated': 7,
        'reviewed': 23}
    updater.update()
    mem_score = UserStoreScore.objects.filter(user=member)
    assert mem_score.get(date=today).suggested == 432
    assert mem_score.get(date=today).score == 10
    assert mem_score.get(date=today).translated == 28
    assert mem_score.get(date=today).reviewed == 0
    today_score = mem_score.get(date=today)
    today_score.reviewed = 99999
    today_score.score = 0
    today_score.save()
    updater.update()
    assert mem_score.get(date=today).suggested == 432
    assert mem_score.get(date=today).score == 10
    assert mem_score.get(date=today).translated == 28
    assert mem_score.get(date=today).reviewed == 0