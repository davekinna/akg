# Import the necessary modules
import matplotlib.pyplot as plt
import pandas as pd


# Initialize the lists for X and Y
df = pd.read_csv('PubMed_Timeline_Results_by_Year.csv')

X = list(df.iloc[:, 0])
Y = list(df.iloc[:, 1])
plt.yticks(range(0, max(Y)+1, 5))

plt.bar(X, Y, color='g')
plt.title("Publications per year for our standard search term")
plt.xlabel("Year")
plt.ylabel("Number of Publications")
plt.savefig('publications_per_year.png')
plt.show()



# import pandas as pd
# import matplotlib.pyplot as plt

# df = pd.read_csv('PubMed_Timeline_Results_by_Year.csv')
# print(df)
# plt.xticks(df['Year'], rotation=45 )

# plt.figure(figsize=(10, 6))
# plt.bar(df['Year'], df['Count'])
# plt.xlabel('Year')
# plt.ylabel('Count of Publications')
# plt.title('Publications per Year')
# plt.tight_layout() # Adjust layout to make room for rotated x-axis labels
# plt.savefig('publications_per_year.png')

# print("Bar chart saved as publications_per_year.png")