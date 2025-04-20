from flask import Flask, jsonify, request
import pymongo
from flask_cors import CORS
import bcrypt
from bson import ObjectId
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

myclient = pymongo.MongoClient(MONGO_URI)
mydb = myclient["SplitX"]
users_collection = mydb["users"]
expense_collection = mydb["expenses"]
group_collection = mydb["groups"]

# Initialize the Flask application
app = Flask(__name__)
CORS(app)

@app.route("/keep-alive", methods=['GET'])
def keep_alive():
    return jsonify({"message": "Hello!"})

@app.route('/users', methods=['GET'])
def users():    
    users_list = []    
    
    for x in users_collection.find({}, {"_id": 0}):
        x.pop("password", None)
        x.pop("friends", None)
        x.pop("expenses", None)
        x.pop("groups", None)
        users_list.append(x)
        
    return jsonify({
        "message": "Success",
        "users": users_list,
    })
        
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()  # Get the JSON data from the request

    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if users_collection.find_one({"email": email}):
        return jsonify({"message": "Email already registered, please use another email!"}), 400
        
    if name and email and password:
        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        current_user = {
            "name": name,
            "email": email,
            "password": hashed_password.decode('utf-8'),
        }
        users_collection.insert_one(current_user)
                    
        return jsonify({
            "message": "Success",
            "input": {
                "name": name,
                "email": email
            },
        }), 201  # Return a "Created" status code
            
    else:
        return jsonify({"message": "Please provide all the required values!"}), 400  # Bad request

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = users_collection.find_one({"email": email})

    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        user.pop("_id", None)  # Safely remove MongoDB ObjectID
        user.pop("password", None)  # Remove password before sending response
        user.pop("friends", None)
        user.pop("expenses", None)
        user.pop("groups", None)
        return jsonify({"message": "Success!", "user": user}), 200
    else:
        return jsonify({"message": "Invalid Credentials!"}), 401

@app.route('/new-friend', methods=['POST'])
def new_friend():
    data = request.get_json()
    friend_email = data.get('email')
    user_email = data.get('currentUserEmail')
    
    if friend_email == user_email:
        return jsonify({"message": "User not found!"}), 404

    friend = users_collection.find_one ({"email": friend_email})
    user = users_collection.find_one ({"email": user_email})

    if not friend or not user:
        return jsonify({"message": "User not found!"}), 404
    
    added_friends = user.get('friends', [])
    for curr_friend in added_friends:
        if curr_friend == friend['_id']:
            return jsonify({"message": "Already a friend!"}), 409

    users_collection.update_one(
        {"email": user_email},
        {"$addToSet": {"friends": friend["_id"]}}
    )

    users_collection.update_one(
        {"email": friend_email},
        {"$addToSet": {"friends": user["_id"]}}
    )
    return jsonify({"message": "Success!"}), 200

def get_friend_details(currentUserEmail, friendEmail):
    currentUser = users_collection.find_one({"email": currentUserEmail})
    friend = users_collection.find_one({"email": friendEmail})

    if not currentUser or not friend:
        return None

    # for common expenses (expenses which involves both the logged in user and the selected friend)
    common_expenses = list(expense_collection.find(
        {"split": {"$all": [friendEmail, currentUserEmail]}}
    )) or []
    
    for expense in common_expenses:
        expense['_id'] = str(expense['_id'])
        if currentUserEmail in expense.get('settled_members'):
            expense['dues_cleared'] = True
        else:
            expense['dues_cleared'] = False

    total_balance = 0 
    for exp in common_expenses:
        # if the current expense is paid by the logged_in user, add the share amount to total balance.
        if exp.get('created_by').get('email') == currentUserEmail:
            total_balance += exp.get('each_share')
        # if it is paid by the selected friend, deduct the share amount from total balance, because the logged_in user owe that money to the friend
        elif exp.get('created_by').get('email') == friendEmail:
            total_balance -= exp.get('each_share')
    
    common_groups = list(group_collection.find(
        {"members": {"$all": [friend.get('_id', currentUser.get('_id'))] }},
        {"group_name": 1, "_id": 0}
    )) or []

    return {
        "name": friend.get('name'),
        "email": friend.get('email'),
        "common_expenses": common_expenses,
        "common_groups": common_groups,
        "total_balance": total_balance,
    }

@app.route("/friends", methods=['POST'])
def friends():
    data = request.get_json()
    user = users_collection.find_one ({"email": data.get('currentUserEmail')})
    currentUserEmail = user.get('email')
    friends = user.get('friends', [])
    friends_list = []
    for curr_friend in friends:
        x = users_collection.find_one ({"_id": curr_friend})
        if x:
            curr_friend_email = x.get('email')
            friend_details = get_friend_details(currentUserEmail, curr_friend_email)
            friends_list.append(friend_details)

    return jsonify({"message": "Success!","friends": friends_list}) ,200

@app.route("/friend/<string:email>", methods=['POST'])
def friend(email):
    data = request.get_json()
    currentUserEmail = data.get('currentUserEmail')

    friend_details = get_friend_details(currentUserEmail, email)
    if not friend_details:
        return jsonify({"message": "User or friend not found"}), 404

    return jsonify({"message": "Success!", "friend_details": friend_details}), 200

@app.route("/new-expense", methods=['POST'])
def new_expense():
    data = request.get_json()
    expense = data.get('newExpense')
    user_email = data.get('currentUserEmail')

    # Validate input
    if not user_email or not expense:
        return jsonify({"message": "Invalid request!"}), 400

    # Check if the user exists
    user = users_collection.find_one({"email": user_email})
    if not user:
        return jsonify({"message": "User not found!"}), 404
    
    expense['each_share'] = round(float(expense.get('amount')) / len(expense.get('split')), 2)
    expense['created_by'] = {"email": user.get('email'), "name": user.get('name')}
    expense['settled_members'] = [user.get('email')]
    expense['unsettled_members'] = []

    # Add expense to database
    expense_collection.insert_one(expense)

    # Add expense reference to each friend's expenses list
    for friend_email in expense.get('split', []):
        friend = users_collection.find_one({"email": friend_email})
        if friend:
            users_collection.update_one(
                {"email": friend_email},
                {"$addToSet": {"expenses": expense["_id"]}}
            )

    # Return clean expense data (without "_id")
    expense.pop("_id", None)

    return jsonify({"message": "Expense added successfully!", "expense": expense}), 201

@app.route("/expenses", methods=['POST'])
def expenses():
    data = request.get_json()
    user_email = data.get('email')
    user = users_collection.find_one({"email": user_email})
    if not user:
        return jsonify({"message": "User does not exists!"})

    expenses = list(expense_collection.find({"split": user_email}))
    # Convert ObjectId to string
    for expense in expenses:
        expense['_id'] = str(expense['_id'])
    
    if expenses:
        return jsonify({"message": "Success!", "expenses": expenses}), 200
    else:
        return jsonify({"message": "No expenses found!", "expenses": []}), 200

@app.route("/expense-details", methods=['POST'])
def get_expense_details():
    req = request.get_json()
    expense_id = req.get('expense_id')
    expense = expense_collection.find_one({"_id": ObjectId(expense_id)})

    members_details = []
    members = expense.get('split')
    created_by_email = expense.get('created_by').get('email')
    for member in members:
        user = users_collection.find_one({"email": member})
        if user:
            if member == created_by_email:
                paid = expense.get('each_share')
                balance = float(expense.get('amount')) - float(paid)
            else:
                if member not in expense.get('settled_members'):
                    paid = 0
                    balance = float(expense.get('each_share')*-1)
                else:
                    paid = expense.get('each_share')
                    balance = float()
        else:
            return jsonify({"message": "user not found!"})
    
        members_details.append(
            {
                "name": user.get('name'),
                "email": member,
                "share": expense.get('each_share'),
                "paid": paid,
                "balance": balance,
            }
        )

    expense['_id'] = str(expense['_id'])

    return jsonify({"message": "success!", "expense": expense, "members_details": members_details})

@app.route("/delete-expense/<string:id>", methods=['DELETE'])
def delete_expense(id):
    expense = expense_collection.find_one({"_id": ObjectId(id)})
    
    if not expense:
        return jsonify({"message": "invalid id"})
    
    expense_collection.delete_one({"_id": expense.get('_id')})
    expense['_id'] = str(expense['_id'])

    return jsonify({"message": "success!","deleted_expense": expense})

@app.route("/new-group", methods=['POST'])
def new_group():
    data = request.get_json()
    email = data.get('email')
    group_name = data.get('group_name')
    members = data.get('members')

    # Validate input
    if not email or not group_name or not members:
        return jsonify({"message": "Incomplete data!"}), 400
    
    # Create a list containing the reference "_id" of users if they exists in the db.
    member_list = []
    for member in members:
        current_member = users_collection.find_one({"email": member})
        if not current_member:
            return jsonify({"message": "User/Members does not exist!"}), 400
        else:
            member_list.append(current_member['_id'])
            if current_member['email'] == email:
                creator_id = current_member['_id']
        
    # Create a group dict for storing in the group_collection in the db 
    group = {
        "created_by": creator_id,
        "group_name": group_name,
        "members": member_list
    }

    group_collection.insert_one(group)
    
    for user_id in member_list:
        current_user = users_collection.find_one({"_id": user_id})
        if current_user:
            users_collection.update_one(
                {"_id": user_id},
                {"$addToSet":{"groups": group['_id']}}
            )

    return jsonify({"message": "Success!", "input": {"created_by": email,"group_name": group_name,"members": members}}), 200

@app.route("/groups", methods=['POST'])
def groups():
    data = request.get_json()
    user_email = data.get('email')

    user = users_collection.find_one({"email": user_email})
    if not user:
        return jsonify({"message": "User does not exists!"})

    groups = list(group_collection.find(
        {"members": user.get('_id')},
        {"_id": 0}
    ))

    if groups:
        for group in groups:
            group.pop("members")
            group.pop("created_by")
        return jsonify({"message": "Success!", "groups": groups}), 200
    else:
        return jsonify({"message": "No groups found!", "groups": []}), 200
    
# Start the Flask app
if __name__ == '__main__':
    app.run(debug=True)