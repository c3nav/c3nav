finalize = {
    hoster: null,
    state: 'checking',
    submittask: null,
    init: function() {
        finalize.hoster = $('#hoster').attr('data-name');
        finalize._set_state('checking');
        finalize._check_hoster();
        sessionStorage.setItem('finalize-data', finalize.get_data());
        $('button[data-oauth]').click(finalize._click_oauth_btn);
        $('button[data-commit]').click(finalize._click_commit_btn);
    },
    get_data: function() {
        return $('#data').val();
    },
    _check_hoster: function() {
        $.getJSON('/api/v1/hosters/'+finalize.hoster+'/state/', function(data) {
            if (data.state == 'checking') {
                window.setTimeout(finalize._check_hoster, 700);
            } else {
                $('#error').text(data.error).toggle(data.error !== null);
                finalize._set_state(data.state);
            }
        });
    },
    _set_state: function(state) {
        finalize.state = state;
        $('.hoster-state').hide().filter('[data-state='+state+']').show();
        $('#alternatively').toggle(['progress', 'done'].indexOf(state) == -1);
    },
    _click_oauth_btn: function() {
        finalize._set_state('oauth');
        $.ajax({
            type: "POST",
            url: '/api/v1/hosters/'+finalize.hoster+'/auth_uri/',
            dataType: 'json',
            headers: {'X-CSRFToken': $('[name=csrfmiddlewaretoken]').val()},
            success: function(data) {
                window.location = data.auth_uri;
            }
        });
    },
    _click_commit_btn: function() {
        var commit_msg = $.trim($('#commit_msg').val());
        if (commit_msg == '') return;
        $('#error').hide();
        finalize._set_state('progress');
        $.ajax({
            type: "POST",
            url: '/api/v1/hosters/'+finalize.hoster+'/submit/',
            data: {
                'data': finalize.get_data(),
                'commit_msg': commit_msg
            },
            dataType: 'json',
            headers: {'X-CSRFToken': $('[name=csrfmiddlewaretoken]').val()},
            success: finalize.handle_task_data
        });
    },
    handle_task_data: function(data) {
        finalize.submittask = data.id
        if (data.done) {
            if (!data.success) {
                $('#error').text(data.error).show();
                finalize._set_state('logged_in');
            } else {
                $('#pull_request_link').attr('href', data.result.url).text(data.result.url);
                finalize._set_state('done');
            }
        } else {
            window.setTimeout(finalize._check_submittask, 700);
        }
    },
    _check_submittask: function() {
        $.getJSON('/api/v1/submittask/'+finalize.submittask+'/', finalize.handle_task_data);
    }
};

if ($('#hoster').length) {
    finalize.init();
}
if ($('#finalize-redirect').length) {
    $('form').append($('<input type="hidden" name="data">').val(sessionStorage.getItem('finalize-data'))).submit();
}
