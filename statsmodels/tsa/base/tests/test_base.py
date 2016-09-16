import numpy as np
import numpy.testing as npt
import pandas as pd
from statsmodels.tsa.base.datetools import _freq_to_pandas
from statsmodels.tsa.base.tsa_model import TimeSeriesModel
from statsmodels.tools.testing import assert_equal


def test_pandas_nodates_index():

    data = [988, 819, 964]
    dates = ['a', 'b', 'c']
    s = pd.Series(data, index=dates)

    npt.assert_raises(ValueError, TimeSeriesModel, s)

    # Test with a non-date index that doesn't raise an exception because it
    # can be coerced into a nanosecond DatetimeIndex
    # (This test doesn't make sense for Numpy < 1.7 since they don't have
    # nanosecond support)
    # (This test also doesn't make sense for Pandas < 0.14 since we don't
    # support nanosecond index in Pandas < 0.14)
    try:
        _freq_to_pandas['N']
        from pandas import version
        if version.version < '0.14':
            raise NotImplementedError
    except:
        pass
    else:
        data = [988, 819, 964]
        # index=pd.date_range('1970-01-01', periods=3, freq='QS')
        index = pd.to_datetime([100, 101, 102])
        actual_str = (index[0].strftime('%Y-%m-%d %H:%M:%S.%f') +
                      str(index[0].value))
        assert_equal(actual_str, '1970-01-01 00:00:00.000000100')
        s = pd.Series(data, index=index)
        mod = TimeSeriesModel(s)
        start = mod._get_predict_start(0)
        end, out_of_sample = mod._get_predict_end(4)
        mod._make_predict_dates()
        assert_equal(len(mod.data.predict_dates), 5)

def test_predict_freq():
    # test that predicted dates have same frequency
    x = np.arange(1,36.)

    # there's a bug in pandas up to 0.10.2 for YearBegin
    #dates = date_range("1972-4-1", "2007-4-1", freq="AS-APR")
    dates = pd.date_range("1972-4-30", "2006-4-30", freq="A-APR")
    series = pd.Series(x, index=dates)
    model = TimeSeriesModel(series)
    #npt.assert_(model.data.freq == "AS-APR")
    npt.assert_(model.data.freq == "A-APR")

    start = model._get_predict_start("2006-4-30")
    end = model._get_predict_end("2016-4-30")
    model._make_predict_dates()

    predict_dates = model.data.predict_dates

    #expected_dates = date_range("2006-12-31", "2016-12-31",
    #                            freq="AS-APR")
    expected_dates = pd.date_range("2006-4-30", "2016-4-30", freq="A-APR")
    assert_equal(predict_dates, expected_dates)
    #ptesting.assert_series_equal(predict_dates, expected_dates)


def test_keyerror_start_date():
    x = np.arange(1,36.)

    # there's a bug in pandas up to 0.10.2 for YearBegin
    #dates = date_range("1972-4-1", "2007-4-1", freq="AS-APR")
    dates = pd.date_range("1972-4-30", "2006-4-30", freq="A-APR")
    series = pd.Series(x, index=dates)
    model = TimeSeriesModel(series)

    npt.assert_raises(ValueError, model._get_predict_start, "1970-4-30")

def test_period_index():
    # test 1285

    dates = pd.PeriodIndex(start="1/1/1990", periods=20, freq="M")
    x = np.arange(1, 21.)

    model = TimeSeriesModel(pd.Series(x, index=dates))
    npt.assert_(model.data.freq == "M")
    model = TimeSeriesModel(pd.Series(x, index=dates))
    npt.assert_(model.data.freq == "M")

def test_pandas_dates():

    data = [988, 819, 964]
    dates = ['2016-01-01 12:00:00', '2016-02-01 12:00:00', '2016-03-01 12:00:00']

    datetime_dates = pd.to_datetime(dates)

    result = pd.Series(data=data, index=datetime_dates, name='price')
    df = pd.DataFrame(data={'price': data}, index=dates)

    model = TimeSeriesModel(df['price'])

    assert_equal(model.data.dates, result.index)
