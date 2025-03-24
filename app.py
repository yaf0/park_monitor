from flask import Flask, render_template, jsonify, request
from flask_compress import Compress
import pymysql
import time
import configparser
from datetime import datetime, timedelta

# 读取 ini 配置
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

# 端口
PORT = int(config["app"]["port"])

# 数据库配置
DB_CONFIG = {
    "host": config["database"]["host"],
    "user": config["database"]["user"],
    "password": config["database"]["password"],
    "database": config["database"]["database"],
    "charset": config["database"]["charset"]
}

# 其他设置
MAX_RECORDS = int(config["settings"]["max_records"])
DISPLAY_HOURS = int(config["settings"]["display_hours"])
PLATE_TABLE = config["settings"]["plate_table"]
PARK_INFO_FAST = config["settings"]["park_info_fast"]
PARK_INFO_SLOW = config["settings"]["park_info_slow"]

app = Flask(__name__)
app.config['COMPRESS_MIN_SIZE'] = 500  # 只有在响应体大于 500 字节时才压缩
app.config['COMPRESS_CACHE'] = True  # 启用缓存压缩后的响应

Compress(app)  # 启用压缩功能


def get_records_by_tab(tab):
    """根据 tab 获取不同表的数据"""
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    # 获取当前时间，并计算出XX小时之前的时间
    now = datetime.now()
    time_threshold = now - timedelta(hours=DISPLAY_HOURS)

    table_name = PARK_INFO_SLOW if tab == 'slow' else PARK_INFO_FAST

    query = f"""
            SELECT pi.plateNum, pi.frameNo, pi.engineNumber, pi.carModel, pi.color, pi.commission, pi.area,
                   p.parkName, p.detailAddress, p.inTime, p.create_time, p.residenceTime, p.company, p.applicant, p.monthlyRent, p.webName, p.state, p.row_num
            FROM {table_name} p
            JOIN {PLATE_TABLE} pi ON p.plateNum = pi.plateNum
            WHERE p.inTime >= %s
            ORDER BY p.create_time DESC
            LIMIT {MAX_RECORDS}
    """
    # query = f"""
    # WITH filtered AS (
    # SELECT pi.plateNum, pi.frameNo, pi.engineNumber, pi.carModel, pi.color, pi.commission, pi.area,p.parkName,
    #  p.detailAddress, p.inTime, p.create_time, p.residenceTime, p.company, p.applicant, p.monthlyRent, p.webName, p.state, p.row_num
    # FROM {table_name} p INNER  JOIN {PLATE_TABLE} pi ON p.plateNum = pi.plateNum
    # WHERE p.intime >= %s OR p.monthlyrent = '是'),
    # ranked AS (SELECT *, ROW_NUMBER() OVER ( PARTITION BY platenum, webname, parkname  ORDER BY row_num DESC ) AS rn FROM filtered)
    # SELECT * FROM ranked WHERE rn = 1 ORDER BY row_num DESC;
    # """
    cursor.execute(query, (time_threshold,))
    records = cursor.fetchall()
    connection.close()

    # 统一处理返回的数据，将 None 转换为空字符串
    for record in records:
        # record.pop("rn", None)
        if record['create_time']:
            record['create_time'] = record['create_time'].strftime('%Y-%m-%d %H:%M:%S')
        if record['inTime']:
            record['inTime'] = record['inTime'].strftime('%Y-%m-%d %H:%M:%S')
        for key, value in record.items():
            if value is None:
                record[key] = ''  # 将 None 值替换为空字符串

    return records





def mark_as_read(row_num, tab):
    """标记记录为已读"""
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor()
    table_name = PARK_INFO_SLOW if tab == 'slow' else PARK_INFO_FAST
    query = f"UPDATE {table_name} SET state='已读' WHERE row_num=%s"
    cursor.execute(query, (row_num,))
    connection.commit()
    connection.close()


def mark_as_unread(row_num, tab):
    """标记记录为未读"""
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor()
    table_name = PARK_INFO_SLOW if tab == 'slow' else PARK_INFO_FAST
    query = f"UPDATE {table_name} SET state=NULL WHERE row_num=%s"
    cursor.execute(query, (row_num,))
    connection.commit()
    connection.close()


def mysql_(plate,sql):
    # 验证车牌号格式（可以根据需求调整）
    if len(plate) < 7 or len(plate) > 8:
        return 'error'

    connection = None
    cursor = None
    retry_count = 3
    current_retry = 0

    try:
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        while current_retry < retry_count:
            try:
                cursor.execute(sql)
                connection.commit()
                return 'ok'

            except Exception as e:
                connection.rollback()
                current_retry += 1
                if current_retry >= retry_count:
                    return 'error'
                time.sleep(1)

    except Exception as e:
        # 处理连接错误
        return 'error'

    finally:
        # 确保资源正确关闭
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def process_plate_info(connection, cursor):
    retry_count = 3  # 设置重试次数
    current_retry = 0

    while current_retry < retry_count:
        try:
            # 连接数据库
            conn = pymysql.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # **1. 更新 plateNum，去掉空格**
            cursor.execute("UPDATE plate_info SET plateNum = REPLACE(plateNum, ' ', '')")
            conn.commit()

            # **2. 处理无效车牌（大小写、空格问题）**
            cursor.execute(
                "SELECT id, plateNum, frameNo FROM plate_info "
                "WHERE BINARY UPPER(plateNum) <> plateNum "
                "OR BINARY plateNum <> TRIM(plateNum) "
                "OR TRIM('\n' FROM TRIM('\t' FROM TRIM(plateNum))) <> plateNum"
            )
            update_data = cursor.fetchall()
            up_show = ''
            update_values = []

            for up in update_data:
                plate = up[1].strip().upper()
                update_values.append((plate, up[0]))
                up_show += f"{plate or ''}, {up[2] or ''}<br>"

            # **批量更新车牌**
            if update_values:
                cursor.executemany("UPDATE plate_info SET plateNum = %s WHERE id = %s", update_values)
                conn.commit()

            # **3. 删除不合格的车牌（长度不符合）**
            cursor.execute(
                "SELECT id, plateNum, frameNo FROM plate_info "
                "WHERE CHAR_LENGTH(plateNum) < 7 OR CHAR_LENGTH(plateNum) > 8 OR plateNum IS NULL"
            )
            del_data = cursor.fetchall()
            del_show = ''
            delete_ids = [d[0] for d in del_data]

            for d in del_data:
                del_show += f"{d[1] or ''}, {d[2] or ''}<br>"

            # **批量删除**
            if delete_ids:
                delete_sql = f"DELETE FROM plate_info WHERE id IN ({','.join(['%s'] * len(delete_ids))})"
                cursor.execute(delete_sql, delete_ids)
                conn.commit()

            # **4. 处理重复车牌（合并相同车牌数据）**
            cursor.execute(
                "SELECT id, plateNum, company, applicant FROM plate_info "
                "WHERE plateNum IN (SELECT plateNum FROM plate_info GROUP BY plateNum HAVING COUNT(*) > 1) "
                "ORDER BY plateNum"
            )
            merge_data = cursor.fetchall()

            record = {}
            merge_show = ''
            for data in merge_data:
                _id, plate_number, company, applicant = data
                if plate_number in record:
                    record[plate_number]['del'].append(_id)
                    record[plate_number]['company'] += f'({company}_{applicant})'
                else:
                    record[plate_number] = {
                        'update': _id,
                        'del': [],
                        'company': company or ''
                    }

            # **执行合并**
            update_statements = []
            delete_statements = []
            for plate, v in record.items():
                update_statements.append((v["company"], v["update"]))
                for _id in v["del"]:
                    delete_statements.append((_id,))
                merge_show += plate + '<br>'

            # **批量更新公司信息**
            if update_statements:
                cursor.executemany("UPDATE plate_info SET company = %s WHERE id = %s", update_statements)
                conn.commit()

            # **批量删除重复数据**
            if delete_statements:
                cursor.executemany("DELETE FROM plate_info WHERE id = %s", delete_statements)
                conn.commit()

            # **返回结果**
            res = f'删除车牌<br>{del_show}<br><br>更新车牌<br>{up_show}<br><br>合并车牌<br>{merge_show}'

            cursor.close()
            conn.close()
            return res

        except pymysql.MySQLError as e:
            print(f"数据库错误: {e}")
            if conn:
                conn.rollback()
                conn.close()
            current_retry += 1
            if current_retry >= retry_count:
                return 'error'
            time.sleep(1)  # 等待 1 秒后重试


@app.route('/')
def index():
    return render_template("index.html")


@app.route('/get_data')
def get_data():
    """API 端点，返回 48 小时内的数据，支持根据 tab 获取不同表的数据"""
    tab = request.args.get('tab', 'fast')  # 获取 URL 参数中的 tab，默认为 fast
    records = get_records_by_tab(tab)
    return jsonify(records)


@app.route('/mark_read', methods=['POST'])
def mark_read():
    tab = request.args.get('tab', 'fast')  # 获取 URL 参数中的 tab，默认为 fast
    data = request.json
    mark_as_read(data['row_num'], tab)
    return jsonify({"status": "success"})


@app.route('/mark_unread', methods=['POST'])
def mark_unread():
    tab = request.args.get('tab', 'fast')  # 获取 URL 参数中的 tab，默认为 fast
    data = request.json
    mark_as_unread(data['row_num'], tab)
    return jsonify({"status": "success"})


@app.route('/search_plate', methods=['GET'])
def search_plate():
    """模糊查询车牌号"""
    plate_num = request.args.get('plateNum', '')  # 获取前端传递的车牌号
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    query = f"""
    SELECT * FROM {PLATE_TABLE} WHERE plateNum LIKE %s
    """
    cursor.execute(query, ('%' + plate_num + '%',))  # 使用 LIKE 进行模糊查询
    records = cursor.fetchall()
    connection.close()
    # 统一处理返回的数据，将 None 转换为空字符串
    for record in records:
        for key, value in record.items():
            if value is None:
                record[key] = ''  # 将 None 值替换为空字符串

    return jsonify(records)


@app.route('/search_records', methods=['GET'])
def search_records_by_plateNum():
    """根据车牌号查询 fast 和 slow 表的数据"""
    plateNum = request.args.get('plateNum', '')  # 获取前端传递的车牌号
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    # 查询 fast 表数据
    query_fast = f"""
    SELECT pi.plateNum, pi.frameNo, pi.engineNumber, pi.carModel, pi.color, pi.commission, pi.area,
           p.parkName, p.detailAddress, p.inTime, p.create_time, p.residenceTime, p.company, p.applicant, p.monthlyRent, p.webName, p.state, p.row_num
    FROM {PARK_INFO_FAST} p
    JOIN {PLATE_TABLE} pi ON p.plateNum = pi.plateNum
    WHERE p.plateNum = %s
    """

    # 查询 slow 表数据
    query_slow = f"""
    SELECT pi.plateNum, pi.frameNo, pi.engineNumber, pi.carModel, pi.color, pi.commission, pi.area,
           p.parkName, p.detailAddress, p.inTime, p.create_time, p.residenceTime, p.company, p.applicant, p.monthlyRent, p.webName, p.state, p.row_num
    FROM {PARK_INFO_SLOW} p
    JOIN {PLATE_TABLE} pi ON p.plateNum = pi.plateNum
    WHERE p.plateNum = %s
    """

    # 执行查询
    cursor.execute(query_fast, (plateNum))
    records_fast = cursor.fetchall()

    cursor.execute(query_slow, (plateNum))
    records_slow = cursor.fetchall()

    # 关闭连接
    connection.close()

    # 合并查询结果
    records = list(records_fast) + list(records_slow)

    # 统一处理返回的数据，将 None 转换为空字符串
    for record in records:
        if record['create_time']:
            record['create_time'] = record['create_time'].strftime('%Y-%m-%d %H:%M:%S')
        if record['inTime']:
            record['inTime'] = record['inTime'].strftime('%Y-%m-%d %H:%M:%S')
        for key, value in record.items():
            if value is None:
                record[key] = ''  # 将 None 值替换为空字符串

    return jsonify(records)


@app.route("/update/<string:plate>/<string:vip>")
def update_plate(plate,vip):
    if not plate:
        return 'error'
    if not vip:
        vip = 1
    # 清理和验证输入
    new_plate = ''.join(plate.strip().split())
    sql = f"UPDATE plate_info SET vip ={vip} WHERE plateNum ='{new_plate}'"
    return mysql_(new_plate,sql)


@app.route("/delete/<string:plate>")
def delete_plate(plate):
    if "'" in plate or "or" in plate:
        return 'error'
    new_plate = ''.join(plate.split())
    sql = f"DELETE FROM plate_info WHERE plateNum = '{new_plate}'"

    return mysql_(new_plate,sql)


@app.route("/deal")
def deal_data():
    connection = None
    cursor = None
    try:
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        return process_plate_info(connection, cursor)

    finally:
        if connection:
            cursor.close()
            connection.close()


if __name__ == '__main__':
    app.run(debug=False, threaded=True, host='0.0.0.0', port=PORT)

