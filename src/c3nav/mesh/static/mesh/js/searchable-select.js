(function () {
    function filterOption(option, value) {
        if (value === '' || option.text.toLowerCase().includes(value)) {
            option.style.display = '';
            return true;
        } else {
            option.style.display = 'none';
            return false;
        }
    }

    function performSearch(select, value) {
        value = value.toLowerCase().trim();
        for (const child of select.children) {
            if (child.nodeName === 'OPTGROUP') {
                let any_visible = false;
                for (const option of child.children) {
                    if (option.nodeName !== 'OPTION') continue;
                    any_visible |= filterOption(option, value);
                }
                if (!any_visible) {
                    child.style.display = 'none';
                } else {
                    child.style.display = '';
                }
            } else if (child.nodeName === 'OPTION') {
                filterOption(child, value);
            }
        }
    }

    function SearchableSelect(select, search) {
        search.addEventListener('input', e => performSearch(select, search.value));
        performSearch(select, search.value);
    }

    window.SearchableSelect = SearchableSelect;
})();