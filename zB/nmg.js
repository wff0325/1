function getAddress(field) {
    var object = { url: field.url, header: "" };
    var res = get.call(object);
    if (res == null) {
        return res;
    }
    var json = JSON.parse(res);
    var item = json.filter((item) => {
        return item.m3u8.indexOf("playlist.m3u8") != -1;
    })

    return JSON.stringify({ url: item[0].m3u8 });
}