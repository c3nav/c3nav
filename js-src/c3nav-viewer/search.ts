
export function c3nav_search(words: string[]): C3NavLocation[] {
    const matches = [];
    for (let i = 0; i < c3nav.locations.length; i++) {
        const location = c3nav.locations[i];
        let leading_words_count = 0;
        let words_total_count = 0;
        let words_start_count = 0;
        let nomatch = false;

        // each word has to be in the location
        for (const word of words) {
            if (location.match.indexOf(word) === -1) {
                nomatch = true;
                break;
            }
        }
        if (nomatch) continue;

        // how many words from the beginning are in the title
        for (let j = 0; j < words.length; j++) {
            let word = words[j];
            if (location.title_words[j] !== word &&
                (j !== words.length - 1 || location.title_words[j].indexOf(word) !== 0)) break;
            leading_words_count++;
        }

        // how many words in total can be found
        for (const word of words) {
            if (location.match.indexOf(' ' + word + ' ') !== -1) {
                words_total_count++;
            } else if (location.match.indexOf(' ' + word) !== -1) {
                words_start_count++;
            }
        }

        matches.push({
            location,
            leading_words_count,
            words_total_count,
            words_start_count
        });
        matches.push([location, leading_words_count, words_total_count, words_start_count, -location.title.length, i])
    }

    matches.sort((a, b) => {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        if (a[4] !== b[4]) return b[4] - a[4];
        return a[5] - b[5];
    });

    return matches.map(match => match[0]);
}


